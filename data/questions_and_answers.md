# Benchmark Questions & Ground Truth Answers

This document lists the benchmark audio questions provided in `data/` and `data/audio/`, along with their transcribed queries, pipeline routing/abstention decisions, target datasets, and verified exact ground truth answers.

---

## 1. Primary Benchmark Queries (`data/`)

### Query 1: Daily Active Users (7-Day Average)
- **Audio File:** [`data/Average.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/Average.mpeg)
- **Transcribed Speech:** *"What's the average active users daily over the last seven days?"*
- **Intent Category:** `ANALYTICS_QUERY`
- **Abstention Decision:** `EXECUTE` (Confidence: 1.0)
- **Data Source:** `analytics.json`
- **Filter / Metric:** `metric == "daily_active_users"` over the 7 most recent recorded dates (`2026-02-10` to `2026-02-16`)
- **Matching Raw Records:**
  | Date | Metric | Value |
  | :--- | :--- | :--- |
  | 2026-02-16 | daily_active_users | 872 |
  | 2026-02-15 | daily_active_users | 162 |
  | 2026-02-14 | daily_active_users | 906 |
  | 2026-02-13 | daily_active_users | 439 |
  | 2026-02-12 | daily_active_users | 391 |
  | 2026-02-11 | daily_active_users | 176 |
  | 2026-02-10 | daily_active_users | 428 |
- **Calculation:**
  $$\text{Sum} = 872 + 162 + 906 + 439 + 391 + 176 + 428 = 3,374$$
  $$\text{Average} = \frac{3,374}{7} \approx 482.0$$
- **Exact Right Answer:** **482 daily active users** (7 records used).
- **Assistant Response:** `"Average value over the period is 482."`

---

### Query 2: General Knowledge (Non-Operational Abstention Test)
- **Audio File:** [`data/Capital.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/Capital.mpeg)
- **Transcribed Speech:** *"Can you tell me what is the capital of France?"*
- **Intent Category:** `GENERAL_KNOWLEDGE` / `NON_DATA_QUERY`
- **Abstention Decision:** `DIRECT` (Confidence: 1.0)
- **Execution Prevented by Abstention:** No (direct LLM answering permitted, all corporate data tools bypassed)
- **Data Source:** None (General World Knowledge)
- **Exact Right Answer:** **Paris**
- **Assistant Response:** `"The capital of France is Paris."`

---

### Query 3: Active Customers List
- **Audio File:** [`data/Customers.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/Customers.mpeg)
- **Transcribed Speech:** *"Show me all the active customers."*
- **Intent Category:** `CRM_QUERY`
- **Abstention Decision:** `EXECUTE` (Confidence: 1.0)
- **Data Source:** `customers.json`
- **Filter / Parameter:** `status == "active"`
- **Total Dataset Size:** 50 customers total (25 active, 25 inactive)
- **Exact Right Answer:** **25 active customers**
- **Matching Customer IDs:**
  `1, 2, 5, 12, 16, 17, 18, 19, 20, 22, 25, 27, 28, 30, 31, 32, 34, 36, 38, 41, 42, 43, 45, 47, 50`
- **Assistant Response:** `"25 records found. Showing first 10."` (Frontend displays `10/25 records` with expandable records dropdown)

---

### Query 4: Closed March Support Tickets (Low Priority)
- **Audio File:** [`data/closed.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/closed.mpeg)
- **Transcribed Speech:** *"Show me all the closed-to-support tickets with low priority created in the month of March."*
- **Intent Category:** `SUPPORT_QUERY`
- **Abstention Decision:** `EXECUTE` (Confidence: 1.0)
- **Data Source:** `support_tickets.json`
- **Filter / Parameters:** `status == "closed"` AND `priority == "low"` AND `month == "March"` (timestamps matching `2026-03-XX`)
- **Matching Raw Records:**
  | Ticket ID | Subject | Priority | Status | Customer ID | Created At |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | 51 | Issue 51 | low | closed | 22 | 2026-03-02T03:46:48.376100 |
  | 52 | Issue 52 | low | closed | 17 | 2026-03-05T03:46:48.376102 |
  | 53 | Issue 53 | low | closed | 27 | 2026-03-09T03:46:48.376104 |
- **Exact Right Answer:** **3 support tickets** (Ticket #51, Ticket #52, Ticket #53)
- **Assistant Response:** `"Found 3 support tickets."`

---

### Query 5: Open High-Priority Support Tickets
- **Audio File:** [`data/high.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/high.mpeg)
- **Transcribed Speech:** *"Can you tell me how many high priority support tickets are still open?"*
- **Intent Category:** `SUPPORT_QUERY`
- **Abstention Decision:** `EXECUTE` (Confidence: 1.0)
- **Data Source:** `support_tickets.json`
- **Filter / Parameters:** `priority == "high"` AND `status == "open"`
- **Total In Dataset:** 60 tickets total; exactly 12 meet both conditions
- **Matching Ticket IDs:**
  `[4, 9, 11, 17, 22, 24, 33, 37, 40, 48, 57, 58]`
- **Exact Right Answer:** **12 open high-priority support tickets**
- **Assistant Response:** `"12 records found. Showing first 10."` (Frontend displays `10/12 records`)

---

### Query 6: Inactive Customers with Open High-Priority Tickets (Cross-Domain Multi-Entity)
- **Audio File:** [`data/inactive.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/inactive.mpeg)
- **Transcribed Speech:** *"How many inactive customers have open high priority tickets?"*
- **Intent Category:** `MULTI_DOMAIN_QUERY`
- **Abstention Decision:** `EXECUTE` (Confidence: 1.0)
- **Data Sources:** `customers.json` (CRM) + `support_tickets.json` (Support)
- **Cross-Domain Correlation Breakdown:**
  1. Retrieve all inactive customers (`status == "inactive"`): **25 customers**
  2. Retrieve all open high-priority tickets (`status == "open"`, `priority == "high"`): **12 tickets**
  3. Correlate by `ticket.customer_id == customer.customer_id`:
     - **Ticket #4** belongs to Customer #35 (*Customer 35*, status: `inactive`)
     - **Ticket #11** belongs to Customer #8 (*Customer 8*, status: `inactive`)
     - **Ticket #22** belongs to Customer #44 (*Customer 44*, status: `inactive`)
     - **Ticket #48** belongs to Customer #4 (*Customer 4*, status: `inactive`)
- **Exact Right Answer:** **4 inactive customers have open high-priority tickets** (affecting 4 tickets: #4, #11, #22, and #48).
- **Assistant Response:** `"Across 25 matching customers and 12 tickets, there are 4 tickets belonging to 4 of those customers."`

---

## 2. Alternate Phrasing Benchmarks (`data/audio/`)

| File Name | Audio Query | Intent / Decision | Exact Right Answer |
| :--- | :--- | :--- | :--- |
| [`data/audio/Average.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/audio/Average.mpeg) | *"Give me the average daily active users."* | `ANALYTICS_QUERY` (`EXECUTE`) | 30 daily data points in dataset; overall average is **546.5** daily active users. |
| [`data/audio/Capital.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/audio/Capital.mpeg) | *"What is the capital city of France?"* | `DIRECT` (Bypasses Tools) | **Paris** |
| [`data/audio/Customers.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/audio/Customers.mpeg) | *"How many active customers do we have?"* | `CRM_QUERY` (`EXECUTE`) | **25 active customers** |
| [`data/audio/closed.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/audio/closed.mpeg) | *"List closed support tickets from this week."* | `SUPPORT_QUERY` (`EXECUTE`) | **0 records** (Tickets in dataset are dated Jan–March 2026; none match the current calendar week). |
| [`data/audio/high.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/audio/high.mpeg) | *"Show me all high priority open tickets."* | `SUPPORT_QUERY` (`EXECUTE`) | **12 support tickets** (IDs: 4, 9, 11, 17, 22, 24, 33, 37, 40, 48, 57, 58). |
| [`data/audio/inactive.mpeg`](file:///d:/Projects/privacy-aware-Voice-Data-Assistant/data/audio/inactive.mpeg) | *"How many inactive customers have opened high priority tickets?"* | `MULTI_DOMAIN_QUERY` (`EXECUTE`) | **4 tickets across 4 inactive customers** (Ticket IDs: 4, 11, 22, 48). |

