# Lab: from credit memo PDFs to a BigQuery table with Gemini

PDFs and AI extraction · 60 minutes, roughly 40 of them hands-on

Hallvik Bank has almost thirty years of credit memos sitting in an archive as PDFs. The old ones were
typed, some are scans of paper forms a branch officer filled in by hand, and the newer ones come out of the
core system. Most are in Swedish, the ones from the Finland and Estonia branches and for international
clients are in English, and the amounts are in SEK or EUR. In this lab you'll turn 40 of them into rows in
BigQuery, find out how often the model gets things wrong, work out what the whole archive would cost, and
then look at how to bring that cost down without losing accuracy.

| Step | | Time |
| --- | --- | --- |
| 0 | Check your dataset | 2 min |
| 1 | Look at the PDFs | 3 min |
| 2 | Read the target schema | 3 min |
| 3 | Pilot: three memos | 8 min |
| 4 | All 40 memos, then validation | 14 min |
| 5 | Cost of the full archive | 4 min |
| 6 | Optimising cost | 8 min |

## What you need

- The project you work in: `ws2026-02`. Location is `EU`.
- Your participant number. You don't need to remember it: step 0 shows you where to find it.
- Yours: the dataset `credit_memos_N`, with your number for N.
- Shared and read-only: the dataset `credit_memos`. It holds the PDFs as a table, two Gemini models, the
  answer key and two reference results I ran before the session.
- The PDFs themselves are in `gs://ws2026-shared-credit-memos/pdf/`.

Gemini calls are billed, so please run the extraction statements as they are and don't widen the pilot to
more files. The memos are synthetic, by the way. Hallvik Bank, its borrowers and its officers don't exist.

## How we share the project

Everyone in the room works in `ws2026-02` at the same time, so the lab keeps your work and your neighbour's
apart. This is what you see in the Explorer, taking participant 7 as an example:

```
ws2026-02
├── credit_memos                shared by everybody, you can only read it
│   ├── memo_files              the 40 PDFs as a table
│   ├── gemini, gemini_lite     the standard model and a smaller, cheaper one
│   ├── labels                  the answer key
│   ├── model_prices            today's prices per model
│   └── extract_reference(_lite)  my runs from before the session
├── credit_memos_7              yours, for this lab
└── external_7, bronze_7, ...   yours too, from the earlier sessions
```

You only see your own datasets and the shared ones. Everybody else's datasets exist too, but they are
invisible to you, just as yours are to them.

Three things keep everybody out of each other's way:

1. **Shared objects can be read by everybody and changed by nobody.** You have read access to
   `credit_memos` and nothing more, so nothing you run can break the PDFs, the models or the labels for the
   rest of the room.
2. **You can only write to your own dataset.** Every query that writes something contains the placeholder
   `credit_memos_N`, which you replace with your dataset. Your rights stop there: you can't see anyone
   else's datasets, and a query that names one by mistake fails with "Access Denied", so a typo can't
   damage anyone else's work.
3. **Forgetting the replacement fails safely.** There is no dataset called `credit_memos_N`, so a query
   where you forgot to replace it stops with "Not found".

One thing we can't separate is Gemini itself. The whole room calls the same models, usually within the same
few minutes of step 4, so calls may get slower or fail with a quota message. That's expected, and step 4
shows you how to deal with it.

---

## Step 0. Check your dataset

Open <https://console.cloud.google.com/bigquery>, pick `ws2026-02` in the project picker at the top, and open
a new query tab with **+**. One tab is enough for the whole lab.

In the Explorer panel on the left, open `ws2026-02`. Next to the shared `credit_memos` you'll see your own
datasets, all ending in the same number, for example `credit_memos_7`. That number is yours for the rest of
the lab.

Every query that touches your own results contains the placeholder `credit_memos_N`. Each time you paste
one, click into the query text first (otherwise Ctrl+H opens the browser's history instead), press
**Ctrl+H**, replace `credit_memos_N` with your dataset (for participant 7 that's `credit_memos_7`) and hit
**Replace all**. Forgetting this is the most common error in this lab, so it's
worth building the habit now. Start with this one:

```sql
SELECT SESSION_USER() AS me, COUNT(*) AS tables_in_my_dataset
FROM credit_memos_N.INFORMATION_SCHEMA.TABLES;
```

You should see your email and `0`: the dataset exists, you can use it, and it's still empty. "Access
Denied" means you typed a number that isn't yours; compare it with the Explorer. If you see no numbered
datasets at all, look at `me`: maybe you're signed in with a different Google account than the one you
registered with. If that's right too, you probably registered late. Let me know, and in the meantime team
up with your neighbour.

To run a single statement, select it and click **Run**. You can run a whole tab, but the console then only
shows the result of the last statement.

---

## Step 1. Look at the PDFs

Before extracting anything, it helps to see what the model is up against. Go to
<https://console.cloud.google.com/storage/browser/ws2026-shared-credit-memos/pdf> (or **Cloud Storage →
Buckets → `ws2026-shared-credit-memos` → `pdf`**) and open these three. Step 3 extracts exactly these:

- `scan_20140324_0705.pdf` is a branch form, scanned, with the fields filled in by hand.
- `KA2002_576.pdf` is a typewritten memo from 2002, with everything in running text.
- `KPM_Nyman_20201028.pdf` comes from the Finland branch. It's in Swedish, but look at the currency.

As you read, look out for a few things. Which currency are the amounts in, and how would you know if
nobody told you? Is income stated per month or per year, and in kronor or in thousands? How is the loan
number written? Is the rating a number or a letter? Did the committee change the risk class the officer
proposed, and where is that recorded? And can you select the text at all, or is the page just a picture?

BigQuery sees the same folder as an object table, one row per file, without copying anything:

```sql
SELECT REGEXP_EXTRACT(uri, r'[^/]+$') AS file_name, content_type, size, updated
FROM credit_memos.memo_files
ORDER BY file_name;
```

You should get 40 rows.

A question for you and your neighbour: if you had to parse these with regular expressions, how many
patterns would you need, and how long would they survive the next template change?

---

## Step 2. Read the target schema

Gemini fills one row per PDF. Amounts stay in the memo's own currency, SEK or EUR, and the currency is a
field of its own. Nothing gets converted.

| Field | Meaning |
| --- | --- |
| `loan_id`, `debtor_id` | Loan and customer numbers, copied exactly as written |
| `currency` | SEK or EUR: the currency of the amounts in this memo |
| `income`, `co_debtor_income`, `household_income` | Gross monthly income |
| `own_funds` | Own funds or cash deposit |
| `credit_rating` | Customer rating from 1 to 5; the old letter ratings map A=1 to E=5 |
| `politically_exposed` | Whether the borrower is a PEP, or `null` if the memo doesn't say |
| `property_country` | SE, FI or EE |
| `reason_for_loan`, `interest_type`, `collateral_type` | Values from fixed lists |
| `initial_credit_limit`, `interest_rate`, `property_value` | Loan amount, rate in %, property value |
| `proposed_risk_class` | The risk class the credit committee decided, from 1 to 5 |
| `risk_class_officer` | What the officer proposed, if the committee overruled it |
| `occupation`, `employer`, `other_debts_total`, `child_ages` | Details that usually exist only in the memo |

The prompt sets a few rules worth knowing about. The model reports the currency but never converts, because
an exchange rate belongs in SQL where you can see and test it. Amounts in thousands get multiplied out, and
yearly incomes get divided by 12. IDs are copied character for character, because cleaning them up is a job
for SQL, not for the model. And if a value isn't in the memo, the answer is `null`, not a plausible guess.

Why copy IDs as written instead of letting the model normalise them? Keep that question in mind; we come
back to it in step 4.

---

## Step 3. Pilot: three memos

### 3.1 What's already there

I created the shared objects in `credit_memos` before the session. You don't need to run this; it's only here so
you can see how the pieces fit together.

```sql
-- the PDFs as rows: object table through the connection that can read the bucket
CREATE EXTERNAL TABLE credit_memos.memo_files
WITH CONNECTION `eu.credit_memos`
OPTIONS (object_metadata = 'SIMPLE', uris = ['gs://ws2026-shared-credit-memos/pdf/*.pdf']);

-- a remote model: forwards rows to Gemini through the same connection
CREATE MODEL credit_memos.gemini
REMOTE WITH CONNECTION `eu.credit_memos`
OPTIONS (ENDPOINT = 'gemini-3.5-flash');
```

The connection `eu.credit_memos` is the only thing holding credentials. It can read the bucket and call
Gemini. You use it through the table and the model, without needing any rights on the bucket or on Gemini
yourself.

One detail worth noticing: because the dataset is in the EU, BigQuery sends the calls to Gemini's EU
endpoint, so the documents are processed in the EU too. With real customer documents that's the first thing
your data protection people will ask about.

### 3.2 Run the pilot

`AI.GENERATE_TABLE` sends each PDF, together with the prompt, to Gemini and returns the schema fields as
ordinary columns. Temperature 0 keeps the answers as repeatable as the model allows. This query is billed,
but it only reads, so there's no `credit_memos_N` to replace.

```sql
SELECT * EXCEPT (prompt, full_response)
FROM AI.GENERATE_TABLE(
  MODEL credit_memos.gemini,
  (
    SELECT
      ('''You read one credit memo of Hallvik Bank, a Nordic bank, for a residential mortgage to private persons.
The memo can be in Swedish or English and from any year between 1996 and 2024: typed, printed by a core
system, or a scanned paper form filled in by hand. Return the fields of the schema. Rules:
- currency is the currency of the amounts in the memo, SEK or EUR. Do not convert between currencies.
- Return amounts in that currency as whole numbers, except interest_rate. Amounts given in thousands
  (tkr, kSEK, kEUR, t€) are multiplied by 1000.
- Incomes are per month. If the memo gives a yearly amount, divide by 12.
- household_income is the income of all borrowers together per month.
- Copy loan_id and debtor_id exactly as written, do not reformat them.
- credit_rating is 1 to 5. An old letter rating maps A=1, B=2, C=3, D=4, E=5.
- If a value is not in the memo, return null. Do not guess.
- proposed_risk_class is the class decided by the credit committee. If the committee changed the
  class proposed by the officer, also by hand, return the committee class; put the officer's
  class in risk_class_officer.
- property_country is the country where the property is located.''', ref) AS prompt,
      uri
    FROM credit_memos.memo_files
    WHERE REGEXP_EXTRACT(uri, r'[^/]+$') IN ('scan_20140324_0705.pdf', 'KA2002_576.pdf', 'KPM_Nyman_20201028.pdf')
  ),
  STRUCT(
    '''memo_ref STRING,
memo_date STRING OPTIONS(description = "date of the memo, YYYY-MM-DD"),
loan_id STRING OPTIONS(description = "loan number exactly as written"),
debtor_id STRING OPTIONS(description = "customer number of the main borrower exactly as written"),
currency STRING OPTIONS(description = "currency of the amounts in the memo, one of: SEK, EUR"),
income INT64 OPTIONS(description = "main borrower gross income per month"),
co_debtor_income INT64 OPTIONS(description = "co-borrower gross income per month, null if none"),
household_income INT64 OPTIONS(description = "all borrowers together, gross income per month"),
own_funds INT64 OPTIONS(description = "own funds or cash deposit available"),
credit_rating INT64 OPTIONS(description = "customer rating 1-5"),
politically_exposed BOOL OPTIONS(description = "null if the memo has no PEP information"),
underage_children_count INT64,
property_country STRING OPTIONS(description = "country of the property, one of: SE, FI, EE"),
reason_for_loan STRING OPTIONS(description = "one of: PURCHASE, REFINANCE, RENOVATION"),
initial_credit_limit INT64 OPTIONS(description = "loan amount"),
interest_type STRING OPTIONS(description = "one of: FIXED, VARIABLE"),
interest_rate FLOAT64 OPTIONS(description = "annual interest rate in percent"),
collateral_type STRING OPTIONS(description = "one of: HOUSE, TERRACED_HOUSE, APARTMENT, HOLIDAY_HOME"),
property_value INT64 OPTIONS(description = "market value of the collateral"),
proposed_risk_class INT64 OPTIONS(description = "final risk class set by the credit committee, 1-5"),
risk_class_officer INT64 OPTIONS(description = "risk class proposed by the credit officer"),
occupation STRING,
employer STRING,
other_debts_total INT64 OPTIONS(description = "sum of other debts listed in the memo, 0 if none"),
child_ages ARRAY<INT64>''' AS output_schema,
    0.0 AS temperature
  )
);
```

Give it up to a minute. You should get three rows with an empty `status` column. Empty means the call
worked; anything else is the error message.

Now put the rows next to the PDFs you opened in step 1. Did it get EUR for the memo from Finland, even
though the text is Swedish? Is the income monthly? Is the risk class the committee's, or did the model take
the officer's? And where it returned `null`, is the value really missing from the document?

---

## Step 4. All 40 memos, then validation

### 4.1 Your bronze table

This creates an empty table in your dataset with the same columns as my reference result. Remember to
replace `credit_memos_N`.

```sql
CREATE TABLE IF NOT EXISTS credit_memos_N.credit_memo_extract
LIKE credit_memos.extract_reference;
```

### 4.2 Extract the rest

Same prompt and schema as the pilot, now over every file. Each result is appended together with its
lineage, as anywhere else in bronze: the source file, the model, the prompt version and a timestamp.

The statement only sends files that don't yet have a successful row. That means retrying is simply running
it again. Files that already worked are never sent twice, and failed attempts stay in the table, so
nothing is overwritten.

This one takes one to three minutes and is the expensive part of the lab. `credit_memos_N` appears twice.

```sql
INSERT INTO credit_memos_N.credit_memo_extract
SELECT
  REGEXP_EXTRACT(uri, r'[^/]+$') AS file_name,
  * EXCEPT (uri, prompt),
  uri AS _source_file,
  'gemini-3.5-flash' AS _model_endpoint,
  'v1' AS _prompt_version,
  CURRENT_TIMESTAMP() AS _ingested_at
FROM AI.GENERATE_TABLE(
  MODEL credit_memos.gemini,
  (
    SELECT
      ('''You read one credit memo of Hallvik Bank, a Nordic bank, for a residential mortgage to private persons.
The memo can be in Swedish or English and from any year between 1996 and 2024: typed, printed by a core
system, or a scanned paper form filled in by hand. Return the fields of the schema. Rules:
- currency is the currency of the amounts in the memo, SEK or EUR. Do not convert between currencies.
- Return amounts in that currency as whole numbers, except interest_rate. Amounts given in thousands
  (tkr, kSEK, kEUR, t€) are multiplied by 1000.
- Incomes are per month. If the memo gives a yearly amount, divide by 12.
- household_income is the income of all borrowers together per month.
- Copy loan_id and debtor_id exactly as written, do not reformat them.
- credit_rating is 1 to 5. An old letter rating maps A=1, B=2, C=3, D=4, E=5.
- If a value is not in the memo, return null. Do not guess.
- proposed_risk_class is the class decided by the credit committee. If the committee changed the
  class proposed by the officer, also by hand, return the committee class; put the officer's
  class in risk_class_officer.
- property_country is the country where the property is located.''', ref) AS prompt,
      uri
    FROM credit_memos.memo_files
    WHERE uri NOT IN (SELECT _source_file FROM credit_memos_N.credit_memo_extract WHERE status = '')
  ),
  STRUCT(
    '''memo_ref STRING,
memo_date STRING OPTIONS(description = "date of the memo, YYYY-MM-DD"),
loan_id STRING OPTIONS(description = "loan number exactly as written"),
debtor_id STRING OPTIONS(description = "customer number of the main borrower exactly as written"),
currency STRING OPTIONS(description = "currency of the amounts in the memo, one of: SEK, EUR"),
income INT64 OPTIONS(description = "main borrower gross income per month"),
co_debtor_income INT64 OPTIONS(description = "co-borrower gross income per month, null if none"),
household_income INT64 OPTIONS(description = "all borrowers together, gross income per month"),
own_funds INT64 OPTIONS(description = "own funds or cash deposit available"),
credit_rating INT64 OPTIONS(description = "customer rating 1-5"),
politically_exposed BOOL OPTIONS(description = "null if the memo has no PEP information"),
underage_children_count INT64,
property_country STRING OPTIONS(description = "country of the property, one of: SE, FI, EE"),
reason_for_loan STRING OPTIONS(description = "one of: PURCHASE, REFINANCE, RENOVATION"),
initial_credit_limit INT64 OPTIONS(description = "loan amount"),
interest_type STRING OPTIONS(description = "one of: FIXED, VARIABLE"),
interest_rate FLOAT64 OPTIONS(description = "annual interest rate in percent"),
collateral_type STRING OPTIONS(description = "one of: HOUSE, TERRACED_HOUSE, APARTMENT, HOLIDAY_HOME"),
property_value INT64 OPTIONS(description = "market value of the collateral"),
proposed_risk_class INT64 OPTIONS(description = "final risk class set by the credit committee, 1-5"),
risk_class_officer INT64 OPTIONS(description = "risk class proposed by the credit officer"),
occupation STRING,
employer STRING,
other_debts_total INT64 OPTIONS(description = "sum of other debts listed in the memo, 0 if none"),
child_ages ARRAY<INT64>''' AS output_schema,
    0.0 AS temperature
  )
);
```

With the whole room calling Gemini at the same moment, it may slow down. If I call it, use this instead. It
copies whatever you're still missing from my reference run, and you carry on with 4.3:

```sql
INSERT INTO credit_memos_N.credit_memo_extract
SELECT * FROM credit_memos.extract_reference
WHERE _source_file NOT IN (SELECT _source_file FROM credit_memos_N.credit_memo_extract WHERE status = '');
```

### 4.3 Did everything come through?

```sql
SELECT
  COUNT(DISTINCT IF(status = '', file_name, NULL)) AS files_ok,
  COUNTIF(status != '') AS failed_attempts,
  ANY_VALUE(IF(status != '', status, NULL)) AS example_error
FROM credit_memos_N.credit_memo_extract;
```

You want `files_ok` at 40. If it's lower and the error mentions quota or "resource exhausted", that's the
room competing for the same capacity. Wait a minute and run 4.2 again; it only picks up what's missing.

### 4.4 How accurate is it?

Since the memos were generated, we know the right answer for every field. It sits in
`credit_memos.labels`, which has 41 rows because one PDF contains two memos. A real archive gives you
nothing like that, which is the point of 4.5.

The query counts, per memo type, currency and scan versus digital, how many memos got each field right.
Amounts count as correct within 1 %, because some memos only show thousands. A `null` counts as correct
where the field genuinely isn't in the document (`fields_not_in_document`).

```sql
WITH e AS (
  SELECT *
  FROM credit_memos_N.credit_memo_extract
  WHERE status = ''
  QUALIFY ROW_NUMBER() OVER (PARTITION BY file_name ORDER BY _ingested_at DESC) = 1
)
SELECT
  g.layout,
  g.currency,
  g.is_scan,
  COUNT(*) AS memos,
  COUNTIF(e.currency = g.currency) AS currency_ok,
  COUNTIF(ABS(e.income - g.income) <= 0.01 * g.income) AS income_ok,
  COUNTIF(ABS(e.household_income - g.household_income) <= 0.01 * g.household_income) AS household_ok,
  COUNTIF(ABS(e.own_funds - g.own_funds) <= 0.01 * g.own_funds
          OR (e.own_funds IS NULL AND STRPOS(IFNULL(g.fields_not_in_document, ''), 'own_funds') > 0)) AS own_funds_ok,
  COUNTIF(e.credit_rating = g.credit_rating) AS rating_ok,
  COUNTIF(e.politically_exposed = g.politically_exposed
          OR (e.politically_exposed IS NULL AND STRPOS(IFNULL(g.fields_not_in_document, ''), 'politically_exposed') > 0)) AS pep_ok,
  COUNTIF(ABS(e.property_value - g.property_value) <= 0.01 * g.property_value) AS property_value_ok,
  COUNTIF(e.proposed_risk_class = g.proposed_risk_class) AS risk_class_ok,
  COUNTIF(ABS(e.other_debts_total - g.other_debts_total) <= 0.01 * g.other_debts_total) AS other_debts_ok
FROM credit_memos.labels g
LEFT JOIN e USING (file_name)
GROUP BY g.layout, g.currency, g.is_scan
ORDER BY g.layout, g.currency, g.is_scan;
```

Which layouts hurt the most, and do the scans drag the numbers down? Is the currency ever wrong, and in
which kind of memo? Then compare with the person next to you: same prompt, same files, temperature 0. Do you
get exactly the same counts?

### 4.5 Checking without an answer key

In production nobody hands you labels. What you can do is check the table against itself. Some values
simply can't be right, such as a household income below the borrower's own income. An income of 40,000 a
month is normal in SEK and very unusual in EUR, so it's a hint the currency is wrong. The same loan
shouldn't turn up in two files. And a field that's `null` in half the rows tells you something too.

Loan numbers are printed in several formats (`L12345678`, `1234-5678`, `1234 5678`). For the duplicate
check the query keeps only the digits, and only for the comparison; the stored values stay as written.
That's the answer to the question from step 2.

```sql
WITH e AS (
  SELECT
    *,
    REGEXP_REPLACE(loan_id, r'[^0-9]', '') AS loan_key
  FROM credit_memos_N.credit_memo_extract
  WHERE status = ''
  QUALIFY ROW_NUMBER() OVER (PARTITION BY file_name ORDER BY _ingested_at DESC) = 1
)
SELECT
  COUNT(*) AS memos,
  -- plausibility
  COUNTIF(household_income < income) AS household_below_income,
  COUNTIF(credit_rating NOT BETWEEN 1 AND 5) AS rating_out_of_range,
  COUNTIF(proposed_risk_class NOT BETWEEN 1 AND 5) AS risk_class_out_of_range,
  COUNTIF(interest_rate NOT BETWEEN 0 AND 15) AS rate_out_of_range,
  COUNTIF(initial_credit_limit > property_value * 1.5) AS loan_above_150pct_of_value,
  -- currency: a monthly income that fits the other currency better
  COUNTIF((currency = 'EUR' AND income > 15000) OR (currency = 'SEK' AND income < 5000)) AS currency_suspect,
  -- duplicates: the same loan in more than one file
  COUNT(loan_key) - COUNT(DISTINCT loan_key) AS duplicate_loans,
  -- completeness (absent from the document, or missed by the model)
  ROUND(COUNTIF(currency IS NULL) / COUNT(*), 2) AS currency_null_rate,
  ROUND(COUNTIF(income IS NULL) / COUNT(*), 2) AS income_null_rate,
  ROUND(COUNTIF(politically_exposed IS NULL) / COUNT(*), 2) AS pep_null_rate,
  ROUND(COUNTIF(property_value IS NULL) / COUNT(*), 2) AS property_value_null_rate
FROM e;
```

If `duplicate_loans` isn't zero and you have a minute, this shows which files share a loan:

```sql
SELECT loan_key, ARRAY_AGG(file_name ORDER BY file_name) AS files
FROM (
  SELECT file_name, REGEXP_REPLACE(loan_id, r'[^0-9]', '') AS loan_key
  FROM credit_memos_N.credit_memo_extract
  WHERE status = ''
  QUALIFY ROW_NUMBER() OVER (PARTITION BY file_name ORDER BY _ingested_at DESC) = 1
)
WHERE loan_key != ''
GROUP BY loan_key
HAVING COUNT(*) > 1;
```

Which of these checks would you make a hard data quality rule? And is a duplicate an error, or just the
same piece of paper scanned twice?

### 4.6 If there's time: the misses

This lists the files where currency, income or risk class came out wrong. The `quirks` column says what was
planted in each memo, which saves you some detective work.

```sql
SELECT g.file_name, g.quirks,
       e.currency, g.currency AS label_currency,
       e.income, g.income AS label_income,
       e.proposed_risk_class, g.proposed_risk_class AS label_risk_class
FROM credit_memos.labels g
LEFT JOIN (
  SELECT * FROM credit_memos_N.credit_memo_extract
  WHERE status = ''
  QUALIFY ROW_NUMBER() OVER (PARTITION BY file_name ORDER BY _ingested_at DESC) = 1
) e USING (file_name)
WHERE e.currency IS DISTINCT FROM g.currency
   OR NOT IFNULL(ABS(e.income - g.income) <= 0.01 * g.income, FALSE)
   OR e.proposed_risk_class IS DISTINCT FROM g.proposed_risk_class
ORDER BY g.file_name;
```

Open a couple of them. Most misses fall into one of three groups. Either the prompt didn't say clearly
enough what to do, or the document itself is the problem (unreadable, or the value just isn't there), or
the schema doesn't fit, like the PDF holding two memos when the table allows one row per file.

---

## Step 5. Cost of the full archive

Gemini charges per token, for what goes in (prompt and PDF pages) and what comes out (the answer, plus any
"thinking" the model does). Every raw response is kept in `full_response`, so we can simply measure it.

### 5.1 Tokens per memo

```sql
SELECT
  COUNT(*) AS memos,
  ROUND(AVG(tokens_in)) AS avg_tokens_in,
  ROUND(AVG(tokens_out)) AS avg_tokens_out,
  ROUND(AVG(tokens_thinking)) AS avg_tokens_thinking
FROM (
  SELECT
    CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.prompt_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.promptTokenCount')) AS INT64) AS tokens_in,
    CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.candidates_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.candidatesTokenCount')) AS INT64) AS tokens_out,
    CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.thoughts_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.thoughtsTokenCount'), '0') AS INT64) AS tokens_thinking
  FROM credit_memos_N.credit_memo_extract
  WHERE status = ''
);
```

If the averages come back empty, the response is shaped differently from what the query expects. Look at
one `full_response` value and find the token counts by eye.

### 5.2 Scale it up

I put today's list prices into `credit_memos.model_prices` before the session; they change too often to
print. Set `archive_memos` to the size of the archive you have in mind and run the block on its own in a
fresh tab, because `DECLARE` has to come first in a script.

```sql
DECLARE archive_memos INT64 DEFAULT 100000;   -- memos in the archive

SELECT
  archive_memos,
  p.model_endpoint,
  ROUND(archive_memos * (t.avg_in * p.usd_per_1m_input + t.avg_out * p.usd_per_1m_output) / 1e6, 2)
    AS usd_one_full_run
FROM (
  SELECT
    AVG(CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.prompt_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.promptTokenCount')) AS INT64)) AS avg_in,
    AVG(CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.candidates_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.candidatesTokenCount')) AS INT64)
        + CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.thoughts_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.thoughtsTokenCount'), '0') AS INT64)) AS avg_out
  FROM credit_memos_N.credit_memo_extract
  WHERE status = ''
) t
JOIN credit_memos.model_prices p ON p.model_endpoint = 'gemini-3.5-flash';
```

That number covers one run. Nobody gets the prompt right first time, so how many runs would you budget
for? That's the question for the last step.

---

## Step 6. Optimising cost

### Where the money goes

Three things decide the bill. Input tokens come almost entirely from the pages: every page is billed at
roughly the same rate, so a blank back side costs as much as a page full of figures, while the prompt itself
is only a few hundred tokens. Output tokens come from the schema and from the model's thinking, and they are
priced several times higher than input. And then there's the number of runs, which nobody puts in the first
estimate.

The goal isn't the lowest price per document. It's the lowest cost per **correct** field. A cheaper model
that makes more mistakes just moves the cost to the people who have to find and fix them.

### Techniques that work on an archive like this one

**Send less to the model.**

- Route by document type. The modern core-system memos are digital and follow fixed templates; a parser on
  the text layer reads them for almost nothing, and the model is only needed for scans, handwriting and the
  old typewritten memos.
- Skip pages that carry nothing: archive cover sheets, scanned blank back sides, attachments you don't need.
  Our archive has all three.
- Deduplicate before you extract. The object table already has a hash per file, so exact copies cost
  nothing to find. A rescan of the same paper has a different hash; that's what the duplicate check in 4.5 is
  for.
- Extract only what you're missing. If the core system already holds income and rating for the newer loans,
  ask the model only for the fields that exist nowhere else.

**Spend less per call.**

- Use the smallest model that meets the accuracy target, and send only the doubtful rows to a stronger one.
  The checks from 4.5 make a good routing rule. You'll try this in 6.2.
- Switch thinking off, or to its lowest level. Reading a form isn't a reasoning task, and thinking tokens
  are billed as output.
- Keep the output small: codes instead of free text, and no "explain your answer" fields.
- Run large backfills in batch mode. Nobody is waiting for the answer, and batch pricing is usually about
  half the interactive price.

**Never pay twice.**

- Run incrementally. Statement 4.2 already does this: only files without a successful row are sent.
- Test a new prompt or model on the labelled sample before you re-run the archive. Forty memos cost next to
  nothing; a full re-run of the archive is the real bill.
- If a prompt change affects one field, re-extract that field with a smaller schema, not the whole row.

Some things sound useful but don't help much here. Prompt caching pays off when a long prompt is reused, and
ours is short next to the document. Downsampling the scans doesn't lower the token count of a PDF page, and it
makes handwriting harder to read.

### 6.1 Compare two models

Before the session I ran all 40 memos through both models. This compares them on five key fields, with
tokens and cost per 1,000 memos. It reads only the two reference tables, so it makes no model calls.

```sql
WITH runs AS (
  SELECT * FROM credit_memos.extract_reference
  UNION ALL
  SELECT * FROM credit_memos.extract_reference_lite
),
scored AS (
  SELECT
    r._model_endpoint AS model,
    CAST(COALESCE(JSON_VALUE(r.full_response, '$.usage_metadata.prompt_token_count'),
                  JSON_VALUE(r.full_response, '$.usageMetadata.promptTokenCount')) AS INT64) AS tokens_in,
    CAST(COALESCE(JSON_VALUE(r.full_response, '$.usage_metadata.candidates_token_count'),
                  JSON_VALUE(r.full_response, '$.usageMetadata.candidatesTokenCount')) AS INT64)
      + CAST(COALESCE(JSON_VALUE(r.full_response, '$.usage_metadata.thoughts_token_count'),
                  JSON_VALUE(r.full_response, '$.usageMetadata.thoughtsTokenCount'), '0') AS INT64) AS tokens_out,
    IF(r.currency = g.currency, 1, 0)
      + IF(ABS(r.income - g.income) <= 0.01 * g.income, 1, 0)
      + IF(ABS(r.property_value - g.property_value) <= 0.01 * g.property_value, 1, 0)
      + IF(r.credit_rating = g.credit_rating, 1, 0)
      + IF(r.proposed_risk_class = g.proposed_risk_class, 1, 0) AS fields_ok
  FROM runs r
  JOIN credit_memos.labels g USING (file_name)
  WHERE r.status = ''
)
SELECT
  s.model,
  COUNT(*) AS memos,
  ROUND(SUM(s.fields_ok) / (5 * COUNT(*)), 3) AS accuracy_5_fields,
  ROUND(AVG(s.tokens_in)) AS avg_tokens_in,
  ROUND(AVG(s.tokens_out)) AS avg_tokens_out,
  ROUND(1000 * (AVG(s.tokens_in) * ANY_VALUE(p.usd_per_1m_input)
              + AVG(s.tokens_out) * ANY_VALUE(p.usd_per_1m_output)) / 1e6, 2) AS usd_per_1000_memos
FROM scored s
LEFT JOIN credit_memos.model_prices p ON p.model_endpoint = s.model
GROUP BY s.model
ORDER BY s.model;
```

Is the small model good enough on its own? Look at where it loses accuracy before you decide; the answer is
usually "on the scans".

### 6.2 Simulate a cascade

The small model reads every memo. Where its answer fails the checks from step 4.5, the memo gets a second
opinion from the standard model. The query shows how many memos get escalated and what that does to
accuracy, compared with either model alone. Again, no model calls.

```sql
WITH lite AS (
  SELECT * FROM credit_memos.extract_reference_lite
  QUALIFY ROW_NUMBER() OVER (PARTITION BY file_name ORDER BY _ingested_at DESC) = 1
),
strong AS (
  SELECT * FROM credit_memos.extract_reference
  WHERE status = ''
  QUALIFY ROW_NUMBER() OVER (PARTITION BY file_name ORDER BY _ingested_at DESC) = 1
),
routed AS (
  SELECT
    l.file_name,
    -- the same checks as in step 4.5, now used to decide who gets a second opinion
    IFNULL(l.status != '' OR l.currency IS NULL OR l.income IS NULL OR l.property_value IS NULL
           OR l.proposed_risk_class IS NULL OR l.household_income < l.income
           OR l.initial_credit_limit > l.property_value * 1.5, TRUE) AS escalate,
    l.currency AS l_currency, l.income AS l_income, l.property_value AS l_value, l.proposed_risk_class AS l_risk,
    s.currency AS f_currency, s.income AS f_income, s.property_value AS f_value, s.proposed_risk_class AS f_risk
  FROM lite l
  LEFT JOIN strong s ON s.file_name = l.file_name
),
scored AS (
  SELECT
    r.escalate,
    IF(r.l_currency = g.currency, 1, 0)
      + IF(ABS(r.l_income - g.income) <= 0.01 * g.income, 1, 0)
      + IF(ABS(r.l_value - g.property_value) <= 0.01 * g.property_value, 1, 0)
      + IF(r.l_risk = g.proposed_risk_class, 1, 0) AS ok_small_only,
    IF(IF(r.escalate, r.f_currency, r.l_currency) = g.currency, 1, 0)
      + IF(ABS(IF(r.escalate, r.f_income, r.l_income) - g.income) <= 0.01 * g.income, 1, 0)
      + IF(ABS(IF(r.escalate, r.f_value, r.l_value) - g.property_value) <= 0.01 * g.property_value, 1, 0)
      + IF(IF(r.escalate, r.f_risk, r.l_risk) = g.proposed_risk_class, 1, 0) AS ok_cascade,
    IF(r.f_currency = g.currency, 1, 0)
      + IF(ABS(r.f_income - g.income) <= 0.01 * g.income, 1, 0)
      + IF(ABS(r.f_value - g.property_value) <= 0.01 * g.property_value, 1, 0)
      + IF(r.f_risk = g.proposed_risk_class, 1, 0) AS ok_strong_only
  FROM routed r
  JOIN credit_memos.labels g USING (file_name)
)
SELECT
  COUNT(*) AS memos,
  COUNTIF(escalate) AS escalated,
  ROUND(SUM(ok_small_only) / (4 * COUNT(*)), 3) AS accuracy_small_only,
  ROUND(SUM(ok_cascade) / (4 * COUNT(*)), 3) AS accuracy_cascade,
  ROUND(SUM(ok_strong_only) / (4 * COUNT(*)), 3) AS accuracy_strong_only
FROM scored;
```

The cascade costs the small model for every memo plus the standard model for the escalated ones. Take the
per-1,000-memo costs from 6.1 and work out whether it's worth it. Would you trust these checks to decide which
memos need a second look?

### 6.3 Optional: the small model yourself

The pilot from step 3 again, this time with the small model, showing the key fields and the tokens per
memo. It's billed, but only three calls.

```sql
SELECT
  REGEXP_EXTRACT(uri, r'[^/]+$') AS file_name,
  currency, income, property_value, proposed_risk_class, status,
  CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.prompt_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.promptTokenCount')) AS INT64) AS tokens_in,
  CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.candidates_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.candidatesTokenCount')) AS INT64)
    + CAST(COALESCE(JSON_VALUE(full_response, '$.usage_metadata.thoughts_token_count'),
                  JSON_VALUE(full_response, '$.usageMetadata.thoughtsTokenCount'), '0') AS INT64) AS tokens_out
FROM AI.GENERATE_TABLE(
  MODEL credit_memos.gemini_lite,
  (
    SELECT
      ('''You read one credit memo of Hallvik Bank, a Nordic bank, for a residential mortgage to private persons.
The memo can be in Swedish or English and from any year between 1996 and 2024: typed, printed by a core
system, or a scanned paper form filled in by hand. Return the fields of the schema. Rules:
- currency is the currency of the amounts in the memo, SEK or EUR. Do not convert between currencies.
- Return amounts in that currency as whole numbers, except interest_rate. Amounts given in thousands
  (tkr, kSEK, kEUR, t€) are multiplied by 1000.
- Incomes are per month. If the memo gives a yearly amount, divide by 12.
- household_income is the income of all borrowers together per month.
- Copy loan_id and debtor_id exactly as written, do not reformat them.
- credit_rating is 1 to 5. An old letter rating maps A=1, B=2, C=3, D=4, E=5.
- If a value is not in the memo, return null. Do not guess.
- proposed_risk_class is the class decided by the credit committee. If the committee changed the
  class proposed by the officer, also by hand, return the committee class; put the officer's
  class in risk_class_officer.
- property_country is the country where the property is located.''', ref) AS prompt,
      uri
    FROM credit_memos.memo_files
    WHERE REGEXP_EXTRACT(uri, r'[^/]+$') IN ('scan_20140324_0705.pdf', 'KA2002_576.pdf', 'KPM_Nyman_20201028.pdf')
  ),
  STRUCT(
    '''memo_ref STRING,
memo_date STRING OPTIONS(description = "date of the memo, YYYY-MM-DD"),
loan_id STRING OPTIONS(description = "loan number exactly as written"),
debtor_id STRING OPTIONS(description = "customer number of the main borrower exactly as written"),
currency STRING OPTIONS(description = "currency of the amounts in the memo, one of: SEK, EUR"),
income INT64 OPTIONS(description = "main borrower gross income per month"),
co_debtor_income INT64 OPTIONS(description = "co-borrower gross income per month, null if none"),
household_income INT64 OPTIONS(description = "all borrowers together, gross income per month"),
own_funds INT64 OPTIONS(description = "own funds or cash deposit available"),
credit_rating INT64 OPTIONS(description = "customer rating 1-5"),
politically_exposed BOOL OPTIONS(description = "null if the memo has no PEP information"),
underage_children_count INT64,
property_country STRING OPTIONS(description = "country of the property, one of: SE, FI, EE"),
reason_for_loan STRING OPTIONS(description = "one of: PURCHASE, REFINANCE, RENOVATION"),
initial_credit_limit INT64 OPTIONS(description = "loan amount"),
interest_type STRING OPTIONS(description = "one of: FIXED, VARIABLE"),
interest_rate FLOAT64 OPTIONS(description = "annual interest rate in percent"),
collateral_type STRING OPTIONS(description = "one of: HOUSE, TERRACED_HOUSE, APARTMENT, HOLIDAY_HOME"),
property_value INT64 OPTIONS(description = "market value of the collateral"),
proposed_risk_class INT64 OPTIONS(description = "final risk class set by the credit committee, 1-5"),
risk_class_officer INT64 OPTIONS(description = "risk class proposed by the credit officer"),
occupation STRING,
employer STRING,
other_debts_total INT64 OPTIONS(description = "sum of other debts listed in the memo, 0 if none"),
child_ages ARRAY<INT64>''' AS output_schema,
    0.0 AS temperature
  )
);
```

---

## For reference

| Object | | What it is |
| --- | --- | --- |
| `credit_memos.memo_files` | shared | The 40 PDFs as an object table |
| `credit_memos.gemini` | shared | Remote model `gemini-3.5-flash`, through the connection `eu.credit_memos` |
| `credit_memos.gemini_lite` | shared | Remote model `gemini-3.5-flash-lite`, the smaller one |
| `credit_memos.labels` | shared | The answer key, only for this lab |
| `credit_memos.model_prices` | shared | List prices per model, set on the day |
| `credit_memos.extract_reference` | shared | My run with the standard model: template for your table, and the fallback |
| `credit_memos.extract_reference_lite` | shared | My run with the small model, for step 6 |
| `credit_memos_N.credit_memo_extract` | yours | One row per extraction attempt, with `_source_file`, `_model_endpoint`, `_prompt_version`, `_ingested_at` |

Your table stands on its own. It isn't joined into silver or gold, and the later sessions don't use it.

## When something goes wrong

| What you see | Likely cause |
| --- | --- |
| `Not found: Dataset ...:credit_memos_N` | The placeholder is still in the query. Ctrl+H, see step 0. |
| `Access Denied` on CREATE or INSERT | You're writing to someone else's dataset, or into `credit_memos`, which is read-only. Check your number. |
| `Not found: Table credit_memos...` | Check the project picker at the top: it should say `ws2026-02`. |
| `Access Denied` already in step 0 | A number that isn't yours: compare it with the Explorer. |
| No numbered datasets in the Explorer | Signed in with another account, or registered late. Tell me, and work with your neighbour for now. |
| `Permission denied` at the very start | Permissions sometimes take a minute to arrive. Try again; if it persists, call me. |
| Results end up in the wrong location | **More → Query settings**, location `EU`. |
| `quota` or `resource exhausted` in `status` | The room is hitting Gemini all at once. Wait a minute, run 4.2 again. |
| 4.2 still running after five minutes | Ask me whether to switch to the reference copy below 4.2. |
| Prices come out as 0 in step 5 or 6 | The prices for the day haven't been filled in yet. Compare tokens instead, and tell me. |
| Only the last result shows up | Select a single statement before clicking **Run**. |
