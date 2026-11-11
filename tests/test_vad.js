/**
 * tests/test_vad.js - Unit tests for Web Audio Voice Activity Detection (VAD) state machine.
 */

const assert = require('assert');

// Mock Web Audio & DOM environment
class MockAnalyserNode {
  constructor() {
    this.fftSize = 512;
    this.smoothingTimeConstant = 0.2;
    this._currentRMS = 0.001; // default silence
  }
  setRMS(val) {
    this._currentRMS = val;
  }
  getFloatTimeDomainData(array) {
    // Fill array with values that produce approximately this._currentRMS
    for (let i = 0; i < array.length; i++) {
      array[i] = this._currentRMS;
    }
  }
  getByteTimeDomainData(array) {
    for (let i = 0; i < array.length; i++) {
      array[i] = Math.min(255, Math.max(0, Math.round(128 + this._currentRMS * 128)));
    }
  }
  disconnect() {
    this.disconnected = true;
  }
}

class MockAudioContext {
  constructor() {
    this.state = 'running';
  }
  createMediaStreamSource(stream) {
    return {
      connect: (target) => { this.connectedTo = target; },
      disconnect: () => { this.disconnected = true; }
    };
  }
  createAnalyser() {
    this.analyser = new MockAnalyserNode();
    return this.analyser;
  }
  close() {
    this.state = 'closed';
    return Promise.resolve();
  }
}

// VAD State Machine Simulator replicating voice_chat.html VAD logic
function createVADSimulator(config = {}) {
  const VAD_CONFIG = {
    SILENCE_THRESHOLD: config.SILENCE_THRESHOLD || 0.015,
    SILENCE_DURATION_MS: config.SILENCE_DURATION_MS || 800,
    SPEECH_TRIGGER_DURATION_MS: config.SPEECH_TRIGGER_DURATION_MS || 150,
    MAX_INITIAL_SILENCE_MS: config.MAX_INITIAL_SILENCE_MS || 12000,
    CHECK_INTERVAL_MS: 30,
  };

  let hasSpoken = false;
  let speechStartTime = null;
  let silenceStartTime = null;
  let isRecording = true;
  let isStopping = false;
  let statusText = 'Listening...';
  let cutoffReason = null;
  let stopCount = 0;
  let cleanupCalled = false;

  const ctx = new MockAudioContext();
  const analyser = ctx.createAnalyser();

  function cleanup() {
    cleanupCalled = true;
    ctx.close();
  }

  function stop(reason) {
    if (!isRecording || isStopping) return;
    isStopping = true;
    isRecording = false;
    stopCount++;
    cutoffReason = reason;
    cleanup();
    isStopping = false;
  }

  function processTick(currentTimeMs, rms) {
    if (!isRecording || isStopping) return;

    if (!hasSpoken) {
      if (rms >= VAD_CONFIG.SILENCE_THRESHOLD) {
        if (!speechStartTime) {
          speechStartTime = currentTimeMs;
        } else if (currentTimeMs - speechStartTime >= VAD_CONFIG.SPEECH_TRIGGER_DURATION_MS) {
          hasSpoken = true;
          silenceStartTime = null;
          statusText = 'Listening (speech detected)...';
        }
      } else {
        speechStartTime = null;
        if (currentTimeMs >= VAD_CONFIG.MAX_INITIAL_SILENCE_MS) {
          statusText = 'No speech detected — finishing recording...';
          stop('initial_timeout');
        }
      }
    } else {
      if (rms < VAD_CONFIG.SILENCE_THRESHOLD) {
        if (!silenceStartTime) {
          silenceStartTime = currentTimeMs;
        } else {
          const silenceElapsed = currentTimeMs - silenceStartTime;
          if (silenceElapsed >= 400 && silenceElapsed < VAD_CONFIG.SILENCE_DURATION_MS) {
            statusText = 'Silence detected — finishing recording...';
          } else if (silenceElapsed >= VAD_CONFIG.SILENCE_DURATION_MS) {
            statusText = 'Silence detected — finishing recording...';
            stop('silence_cutoff');
          }
        }
      } else {
        silenceStartTime = null;
        statusText = 'Listening (speech detected)...';
      }
    }
  }

  return {
    VAD_CONFIG,
    ctx,
    analyser,
    processTick,
    stop,
    getState: () => ({
      hasSpoken,
      isRecording,
      isStopping,
      statusText,
      cutoffReason,
      stopCount,
      cleanupCalled,
    })
  };
}

// ----------------------------------------------------------------------------
// Test Cases
// ----------------------------------------------------------------------------

console.log("Running VAD JavaScript Unit Tests...\n");

// Test 1: Initial silence does NOT trigger premature cutoff
{
  const vad = createVADSimulator();
  // User stays silent for 1500ms
  for (let t = 0; t <= 1500; t += 30) {
    vad.processTick(t, 0.003); // below threshold
  }
  const state = vad.getState();
  assert.strictEqual(state.hasSpoken, false, "Should not mark spoken during initial silence");
  assert.strictEqual(state.isRecording, true, "Should continue recording despite initial 1.5s silence");
  assert.strictEqual(state.stopCount, 0, "Initial silence must not trigger stop");
  console.log("✓ Test 1 Passed: Initial silence does not cause premature termination.");
}

// Test 2: Speech activity triggers hasSpoken state
{
  const vad = createVADSimulator();
  // 500ms initial silence
  for (let t = 0; t <= 500; t += 30) {
    vad.processTick(t, 0.002);
  }
  // User starts speaking (RMS = 0.05) for 200ms (> 150ms trigger duration)
  for (let t = 530; t <= 750; t += 30) {
    vad.processTick(t, 0.05);
  }
  const state = vad.getState();
  assert.strictEqual(state.hasSpoken, true, "Speech should be acknowledged after >= 150ms");
  assert.strictEqual(state.statusText, 'Listening (speech detected)...');
  assert.strictEqual(state.isRecording, true);
  console.log("✓ Test 2 Passed: Speech onset is recognized and activates speech state.");
}

// Test 3: Brief inter-word pauses reset silence timer without cutoff
{
  const vad = createVADSimulator();
  // 200ms speech onset
  for (let t = 0; t <= 200; t += 30) {
    vad.processTick(t, 0.06);
  }
  assert.strictEqual(vad.getState().hasSpoken, true);

  // 350ms natural pause between words (silence < 800ms)
  for (let t = 230; t <= 580; t += 30) {
    vad.processTick(t, 0.004);
  }
  assert.strictEqual(vad.getState().isRecording, true, "Pause < 800ms must not trigger stop");

  // User resumes speaking next word (RMS = 0.08)
  for (let t = 610; t <= 800; t += 30) {
    vad.processTick(t, 0.08);
  }
  assert.strictEqual(vad.getState().isRecording, true);
  assert.strictEqual(vad.getState().statusText, 'Listening (speech detected)...');
  console.log("✓ Test 3 Passed: Short conversational pauses reset silence timer cleanly.");
}

// Test 4: Sustained silence >= 800ms triggers automatic cutoff
{
  const vad = createVADSimulator();
  // 300ms speech
  for (let t = 0; t <= 300; t += 30) {
    vad.processTick(t, 0.08);
  }
  // User finishes utterance; sustained silence begins
  let stoppedAt = null;
  for (let t = 330; t <= 1500; t += 30) {
    vad.processTick(t, 0.002);
    if (!vad.getState().isRecording && stoppedAt === null) {
      stoppedAt = t;
    }
  }
  const state = vad.getState();
  assert.strictEqual(state.isRecording, false, "Recording should stop after sustained silence");
  assert.strictEqual(state.stopCount, 1, "Stop should execute exactly once");
  assert.strictEqual(state.cutoffReason, 'silence_cutoff');
  assert.strictEqual(state.cleanupCalled, true, "Resources must be cleaned up on cutoff");
  // Expected stop time: ~300ms + 800ms = ~1100ms
  assert(stoppedAt >= 1100 && stoppedAt <= 1160, `Stopped at ${stoppedAt}ms, expected ~1100-1160ms`);
  console.log("✓ Test 4 Passed: Sustained silence (>= 800ms) triggers automatic cutoff and resource cleanup.");
}

// Test 5: Manual stop takes precedence during silence
{
  const vad = createVADSimulator();
  // 300ms speech
  for (let t = 0; t <= 300; t += 30) {
    vad.processTick(t, 0.05);
  }
  // 400ms silence
  for (let t = 330; t <= 730; t += 30) {
    vad.processTick(t, 0.003);
  }
  // User manually clicks Stop before 800ms silence threshold is reached
  vad.stop('manual');
  const state = vad.getState();
  assert.strictEqual(state.isRecording, false);
  assert.strictEqual(state.cutoffReason, 'manual', "Manual stop reason must take precedence");
  assert.strictEqual(state.stopCount, 1, "Exactly one stop executed");

  // Subsequent ticks do nothing
  for (let t = 760; t <= 1500; t += 30) {
    vad.processTick(t, 0.001);
  }
  assert.strictEqual(vad.getState().stopCount, 1, "No secondary stop triggered");
  console.log("✓ Test 5 Passed: Manual stop takes immediate precedence over auto-stop.");
}

// Test 6: Quiet speech handling
{
  const vad = createVADSimulator({ SILENCE_THRESHOLD: 0.015 });
  // Quiet speech with RMS = 0.020 (above 0.015 threshold)
  for (let t = 0; t <= 1000; t += 30) {
    vad.processTick(t, 0.020);
  }
  const state = vad.getState();
  assert.strictEqual(state.hasSpoken, true);
  assert.strictEqual(state.isRecording, true, "Quiet speech above threshold must not trigger silence cutoff");
  console.log("✓ Test 6 Passed: Quiet speech above threshold is sustained without cutoff.");
}

// Test 7: Multiple duplicate stop calls execute finalization strictly once
{
  const vad = createVADSimulator();
  vad.stop('manual');
  vad.stop('manual');
  vad.stop('silence_cutoff');
  assert.strictEqual(vad.getState().stopCount, 1, "Multiple stop calls must be idempotent");
  console.log("✓ Test 7 Passed: Stop operation is idempotent with exactly one finalization.");
}

console.log("\nALL 7 VAD JAVASCRIPT TESTS PASSED SUCCESSFULLY!\n");
