You are orchestrating the AI RSS pipeline. Follow these steps:

## Step 1: Fetch new articles
Run: `python f:\project\rss\cli.py fetch`
Report how many new articles were fetched.

## Step 2: Prepare unscored articles
Run: `python f:\project\rss\cli.py score prepare --limit 20`
This outputs JSON with articles and the user's interests.

## Step 3: Score each article
Read the JSON output from Step 2. For each article, evaluate:
- **relevance** (0-10): How well does this match the user's interests in interests.yaml?
- **significance** (0-10): Is this objectively important, novel, or noteworthy?
- **summary**: 1-2 sentence TL;DR
- **topics**: List of classification tags
- **reason**: Brief explanation of the score

Build a JSON array of scores.

## Step 4: Write scores to database
Save the scores JSON to a temp file, then run:
`python f:\project\rss\cli.py score write-file <path-to-temp-file>`

## Step 5: Present top articles
Run: `python f:\project\rss\cli.py score prepare` to confirm no unscored articles remain.
Then present the top-scoring articles (relevance >= 7) to the user in a readable format:
- Title (linked to URL)
- Score: relevance/significance
- Summary
- Topics
