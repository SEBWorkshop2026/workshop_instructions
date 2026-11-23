# Build a data warehouse with Dataform

In this workshop, build a warehouse from six synthetic banking sources. Three
are shared BigQuery tables and three are CSV files in Cloud Storage. Follow
the steps below to declare the sources, load them through bronze and silver,
and build the gold models.

The [`wokrshop_steps/`](wokrshop_steps/) folder contains the project files for
each step. These are cumulative snapshots: each later folder includes the files
from the earlier steps. Use the folders as references when creating or
checking files in your Dataform workspace.
Open the numbered folder for the stage you are working on and use
its files at the matching paths in your workspace.

## Open and configure your workspace

1. In Google Cloud Console, select Workshop 02 and open **Dataform**.
2. Open your assigned repository, `participant-N`, create a development
   workspace, and initialize it if prompted. Remove any sample definitions
   created during initialization so they do not run with the workshop.
3. Use the uploader below, or create the files manually using
   [step 1](wokrshop_steps/01-sources/).
4. For manual runs, choose **Execute with user credentials**.

The repository workspace override selects your project and adds your
participant number to output dataset names, such as `bronze_1`. Keep dataset
names unsuffixed in the SQLX files and workflow settings,

## Skip a step using Cloud shell

You can skip certain steps, if you are lazy and don't want to type out all of the sqlx files by hand.
I do recommend you to type out at least first couple of files in the step so that you fully understand what are we doing and the skip repetition.

To skip a step:

1. In Google Cloud Console, open **Activate Cloud Shell** and authorize it if
   prompted. Create and initialize your Dataform workspace first.
2. Download the uploader:

   ```sh
   curl -fsSLo upload_step.py https://raw.githubusercontent.com/SEBWorkshop2026/workshop_instructions/main/dataform/wokrshop_steps/upload_step.py
   ```
3. Run it with your participant number, your workspace ID and the step number:

   ```sh
   python3 upload_step.py --participant PARTICIPANT_NUMBER --workspace YOUR_WORKSPACE --step 1
   ```
   The uploader replaces differing files included in the selected step by
   default. Files outside that snapshot are left in the workspace; review any
   extra definition files it reports, since they may also run during
   compilation.
4. Return to Dataform, check the workspace compilation and run the actions for
   the exercise with **Execute with user credentials**. Uploading only writes
   workspace files; it does not commit them or execute the workflow.

## Workshop steps

### 1. Declare the shared sources

Use the files in [step 1](wokrshop_steps/01-sources/) to configure workflow
settings, reusable includes, and declarations for the three existing BigQuery
tables: `arrangement_account_info`, `debtor_info`, and `defaults`. A
declaration gives Dataform the name and location of an existing table; it
doesn't copy or create that source table. The reusable `reportingDate` include
converts `2025-03` into `2025-03-01`, which is the date used to select a
monthly snapshot. Compile the workspace and confirm that the declarations
appear in the dependency graph without errors.

### 2. Create external tables

Use [step 2](wokrshop_steps/02-external/) to add external tables for the three
CSV sources in Cloud Storage. Run the workspace and confirm the external
tables are available in the `external` dataset. These tables read CSV files
from the shared bucket; they do not copy all CSV rows into BigQuery. The
bucket and file paths are built using `csv_bucket` and the shared folder
conventions.

### 3. Load the bronze layer

Use [step 3](wokrshop_steps/03-bronze/) to ingest the six sources into
monthly-partitioned bronze tables. The CSV models select the file for the
configured reporting month. Bronze CSV rows also retain ingestion time and
source-file metadata. Each model filters on the selected reporting date, so
running March does not load rows from other months. On a rerun, the model
replaces that month's rows and leaves other reporting months intact. Run the
workspace and confirm the six tables are created in `bronze_N`.

### 4. Clean the data in silver

Use [step 4](wokrshop_steps/04-silver/) to add one silver model per bronze
table. These models select and clean columns without joining sources. Run the
workspace and confirm the six tables are created in `silver_N`; check that
the account origination and maturity columns are dates. For example, the
account dates arrive as `YYYYMMDD` values and are parsed into BigQuery `DATE`
columns here. The debtor identifier is also renamed to `debtor_id`, and
duplicate defaults within a reporting snapshot are removed.

### 5. Build the gold layer

Use [step 5](wokrshop_steps/05-gold/) to build the dimensions, bridge, facts,
and the combined `loan_obt` snapshot. Run the workspace and confirm that the
gold models and assertions succeed. The `gold_N` dataset should contain the
star-schema tables, `loan_obt`, and assertion views. Check that `loan_obt` has
one row per loan and reporting date. Gold models join records from the same
reporting month as well as by entity ID; joining only by loan or debtor ID
could mix attributes from different monthly snapshots. `loan_obt` combines
the loan balance with matching debtor, co-debtor, collateral, and default
records.
