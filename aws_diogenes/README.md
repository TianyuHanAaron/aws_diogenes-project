# aws_diogenes

`aws_diogenes` is a crewAI flow that collects news, trusted social posts, seasonal events, and local photos, then produces a curated email digest plus a trusted-posts summary artifact.

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
uv run run_with_trigger '{"location":"sydney","topic":"energy transition","user_id":"demo_user"}'
```

## Outputs

Running the flow writes:

- `curated_email.html`
- `trusted_posts_digest.txt`

## Project Layout

- `src/aws_diogenes/main.py`: flow entrypoint
- `src/aws_diogenes/crews/trust_posts/`: trusted-post processing crew
- `src/aws_diogenes/crews/curated_emails/`: digest generation crew
- `src/aws_diogenes/tools/`: data fetch and delivery tools
