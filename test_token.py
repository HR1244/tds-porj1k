import os
from openai import OpenAI

token = "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjIzZjEwMDA2ODZAZHMuc3R1ZHkuaWl0bS5hYy5pbiIsImlhdCI6MTc4NTAzNDk5MiwiaXNzIjoiaHR0cHM6Ly9haXBpcGUub3JnIiwiYXVkIjoiYWlwaXBlLWFwaSIsImV4cCI6MTc4NTYzOTc5Mn0.Zl5XCZOFa51kdcnJ0MPtfPMwZEMwNcwZhwsZ4fWv9Nw"

urls_to_try = [
    "https://aipipe.org/openai/v1",
    "https://aipipe.org/api/openai/v1",
    "https://aipipe.org/v1/openai",
    "https://api.aipipe.org/openai/v1"
]

for url in urls_to_try:
    print(f"Trying base_url: {url}")
    try:
        client = OpenAI(api_key=token, base_url=url)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10
        )
        print(f"SUCCESS with {url}: {response.choices[0].message.content}")
        break
    except Exception as e:
        print(f"FAILED with {url}: {e}")
