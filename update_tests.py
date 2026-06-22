import os

replacements = {
    "mock_openai_client": "mock_embeddings_model",
    "_get_openai_client": "_get_embeddings_model",
    "mock_anthropic_client": "mock_chat_model",
    "_get_anthropic_client": "_get_agent_llm",
    "mock_openai_client.embeddings.create = AsyncMock(side_effect=Exception(\"OpenAI rate limit\"))": "mock_embeddings_model.aembed_documents = AsyncMock(side_effect=Exception(\"OpenAI rate limit\"))",
    "mock_anthropic_client.messages.create = AsyncMock(side_effect=Exception(\"Anthropic rate limit\"))": "mock_chat_model.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=Exception(\"Anthropic rate limit\"))",
    "mock_anthropic_client.messages.create = AsyncMock(side_effect=Exception(\"Vision API error\"))": "mock_chat_model.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=Exception(\"Vision API error\"))"
}

def process_file(path):
    with open(path, "r") as f:
        content = f.read()
    original_content = content
    for old, new in replacements.items():
        content = content.replace(old, new)
        
    if "test_image_agent" in path:
        content = content.replace("_get_agent_llm", "_get_image_agent_llm")
        
    if content != original_content:
        with open(path, "w") as f:
            f.write(content)
        print(f"Updated {path}")

for root, _, files in os.walk("tests"):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))
