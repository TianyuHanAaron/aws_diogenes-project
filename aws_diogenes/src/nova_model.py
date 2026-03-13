from crewai import LLM

nova_lite = LLM(
    model="bedrock/amazon.nova-lite-v1:0",
    temperature=0.2,
    max_tokens = 2600,
    top_p = 0.9,
    top_k = 50,
    stop_sequences = ["END"],
)