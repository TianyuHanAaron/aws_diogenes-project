import boto3
import json
import logging


logger = logging.getLogger(__name__)

def suggests_channels(interests):

    prompt = f"""
    A user has following interests:
    
    {', '.join(interests)}
    Available News Channel:
    Global
    Local
    Investment
    Interested Topic
    
    Select the most relevant channels for the user,
    return a JSON list only.
    """

    body = {
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 300
    }

    try:
        client = boto3.client("bedrock-runtime")
        response = client.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        text = result["output"]["message"]["content"][0]["text"]
        channels = json.loads(text)
        return channels
    except Exception as exc:
        logger.warning("Nova channel suggestion failed: %s", exc)
        return ["interest"]
