# diogenes_sunlight_post

`diogenes_sunlight_post` is a digest generator that collects news, seasonal events, webcams, and local photos, then renders a curated HTML email.

## Architecture

The active runtime path is intentionally split into four layers:

- `src/main.py`
  The CrewAI Flow entrypoint. It collects inputs, renders the digest, routes
  delivery, and saves the final HTML.
- `src/services/digest_pipeline.py`
  The orchestration layer. It fetches source data, calls the section helpers,
  injects the rendered sections into the email template, and persists send
  metadata.
- `src/crews/*`
  YAML-driven editorial helpers. These use Amazon Nova Lite to turn raw source
  material into publishable section content:
  - `news_digest`
  - `seasonal_events`
  - `photo_album`
- `src/tools/*`
  Provider-specific data fetchers and delivery helpers for news, photos,
  seasonal search, webcams, and SES email sending.

If you are inspecting the project for the first time, the easiest reading order
is:

1. `src/main.py`
2. `src/services/digest_pipeline.py`
3. `src/crews/news_digest/news_digest.py`
4. `src/crews/seasonal_events/seasonal_events.py`
5. `src/crews/photo_album/photo_album.py`
6. `src/tools/*`

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

For the local interactive CLI:

```bash
uv run run_cli
```

If you are running directly from the source tree or inside the Docker image:

```bash
python -m cli
```

For a locally built Docker image, run the CLI interactively with a TTY, for example:

```bash
docker run --rm -it --entrypoint python <your-image-tag> -m cli
```

## Outputs

Running the flow writes:

- `email_digest.html`

When running in AWS Lambda, the file is written to `/tmp/email_digest.html`.

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

## Project Layout

- `src/main.py`: flow entrypoint
- `src/services/digest_pipeline.py`: orchestration and HTML rendering
- `src/crews/news_digest/`: YAML-driven news section prompts
- `src/crews/seasonal_events/`: YAML-driven seasonal section prompts
- `src/crews/photo_album/`: YAML-driven photo album prompts
- `src/tools/`: data fetch and delivery tools
- `src/models.py`: shared request, content, and flow-state models
- `src/templates/email_template.html`: final HTML email skeleton
