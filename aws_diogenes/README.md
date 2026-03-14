# aws_diogenes

`aws_diogenes` is a crewAI flow that collects news, seasonal events, and local photos, then produces a curated email digest.

## Setup

Use Python `>=3.10,<3.14`.

Install dependencies with your preferred tool. For example:

```bash
uv sync
```

## Required Environment Variables

The runtime tools expect these environment variables:

```bash
export NEWSAPI_API_KEY=your_newsapi_key
export AWS_REGION=ap-southeast-2
export AWS_SES_SOURCE_EMAIL=verified-sender@example.com
```

Notes:

- `NEWSAPI_API_KEY` is required by the news fetch tool.
- `AWS_REGION` or `AWS_DEFAULT_REGION` is recommended for SES/SNS clients.
- `AWS_SES_SOURCE_EMAIL` is required only when using the SES send tool.

## Running

From the project root:

```bash
uv run kickoff
```

Or pass a trigger payload:

```bash
uv run run_with_trigger '{"location":"sydney","hemisphere":"southern","topic":"energy transition","channels":["global","interest"],"interests":["astronomy"]}'
```

## Outputs

Running the flow writes:

- `curated_email.html`

When running in AWS Lambda, the file is written to `/tmp/curated_email.html`.

## AWS Scheduling

This repo includes a Lambda entrypoint and AWS SAM template for scheduled runs
with EventBridge Scheduler.

Key files:

- `src/lambda_handler.py`
- `template.yaml`
- `requirements.txt`

Typical deployment flow:

```bash
sam build
sam deploy --guided
```

Important:

- the Lambda is packaged as a container image, not a zip archive
- Docker must be installed and running for `sam build`
- SAM will build from `Dockerfile` and push the image during deploy

The template provisions:

- one Lambda function that runs the digest
- one EventBridge Scheduler schedule
- one IAM role allowing the schedule to invoke Lambda

Before deploying, authenticate to AWS and provide the required API keys and
sender email as SAM parameter values or stack configuration.

For seasonal event search, this deployment expects `FIRECRAWL_API_KEY` instead
of `OPENAI_API_KEY`.

## Project Layout

- `src/aws_diogenes/main.py`: flow entrypoint
- `src/aws_diogenes/crews/curated_emails/`: digest generation crew
- `src/aws_diogenes/tools/`: data fetch and delivery tools
