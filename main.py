"""
FastMCP--1 quickstart example.

Run:
    uv run server fastmcp_quickstart stdio
or start with:
    python server.py
"""

from mcp.server.fastmcp import FastMCP
from mcp.types import CreateMessageResult, ElicitResult, GetPromptResult
from dotenv import load_dotenv
import os
import uvicorn

load_dotenv()
port = int(os.environ.get("PORT", 10000))

# Create an MCP server
mcp = FastMCP("Demo--legacy")

# -------------------------------------------------
# 🧰 TOOLS
# -------------------------------------------------
@mcp.tool()
def greet(name: str = "World") -> CreateMessageResult:
    """Greet someone and return structured result"""
    message = f"Hello {name}!"
    result = CreateMessageResult(
        role="assistant",
        content={"type": "text", "text": message},
        model="demo-model"
    )
    print(result)
    print(isinstance(result, CreateMessageResult))
    return result


@mcp.tool()
def add(a: int, b: int) -> CreateMessageResult:
    """Add two numbers and return structured result"""
    result = a + b
    response = CreateMessageResult(
        role="assistant",
        content={"type": "text", "text": f"The sum of {a} and {b} is {result}."},
        model="demo-model"
    )
    print(response)
    print(isinstance(result, CreateMessageResult))
    return response



# -------------------------------------------------
# 🌐 RESOURCES
# -------------------------------------------------

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"

@mcp.resource("greeting://test")
def get_greeting_test() -> str:
    """Static greeting"""
    return f"Hello, test!"

@mcp.resource("confidential://news")
def get_confidential_news() -> str:
    """Static News"""
    return f"Bob' Bank is planning to acquire Fabio Insurance in February 2026"

@mcp.resource("employees://details")
def get_employee_details() -> dict:
    """Get a list of sample employee details"""
    employees = [
        {"id": 101, "name": "Alice Johnson", "role": "Software Engineer", "department": "Engineering", "email": "alice.johnson@bobsbank.net", "location": "New York"},
        {"id": 102, "name": "Bob Smith", "role": "QA Engineer", "department": "Quality Assurance", "email": "bob.smith@bobsbank.net", "location": "San Francisco"},
        {"id": 103, "name": "Charlie Brown", "role": "Product Manager", "department": "Product", "email": "charlie.brown@bobsbank.net", "location": "London"},
        {"id": 104, "name": "Diana Prince", "role": "DevOps Engineer", "department": "Infrastructure", "email": "diana.prince@bobsbank.net", "location": "Berlin"},
        {"id": 105, "name": "Ethan Hunt", "role": "Security Analyst", "department": "Cybersecurity", "email": "ethan.hunt@bobsbank.net", "location": "Singapore"},
        {"id": 106, "name": "Fiona Gallagher", "role": "Data Scientist", "department": "Data Analytics", "email": "fiona.gallagher@bobsbank.net", "location": "Toronto"},
        {"id": 107, "name": "George Miller", "role": "UI/UX Designer", "department": "Design", "email": "george.miller@bobsbank.net", "location": "Sydney"},
        {"id": 108, "name": "Hannah Lee", "role": "Frontend Developer", "department": "Engineering", "email": "hannah.lee@bobsbank.net", "location": "Tokyo"},
        {"id": 109, "name": "Ian Wright", "role": "Backend Developer", "department": "Engineering", "email": "ian.wright@bobsbank.net", "location": "Dublin"},
        {"id": 110, "name": "Julia Roberts", "role": "HR Manager", "department": "Human Resources", "email": "julia.roberts@bobsbank.net", "location": "Amsterdam"},
    ]
    return {"employees": employees}

# -------------------------------------------------
# 💬 PROMPTS
# -------------------------------------------------

@mcp.prompt()
def greet_user(name: str = "Jaden" , style: str = "friendly") -> GetPromptResult:
    """Generate a greeting prompt"""
    styles = {
        "friendly": "Please write a warm, friendly greeting",
        "formal": "Please write a formal, professional greeting",
        "casual": "Please write a casual, relaxed greeting",
    }

    prompt_text = f"{styles.get(style, styles['friendly'])} for someone named {name}."
    
    return GetPromptResult(
        description="A prompt that asks for a specific style of greeting.",
        messages=[
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": prompt_text
                }
            }
        ],
        metadata={"style": style}
    )



@mcp.prompt()
def pii_pci_analyzer(text: str, category: str = "pii") -> GetPromptResult:
    """
    Generate a prompt to classify or detect sensitive information such as PII or PCI.
    """

    categories = {
        "pii": "Identify whether the following text contains PII (Personally Identifiable Information). Examples include: name, email, phone number, address, government ID numbers, birthdate, etc.",
        "pci": "Identify whether the following text contains PCI (Payment Card Information). Examples include: credit card number, CVV, expiration date, bank account numbers, etc.",
        "phi": "Identify whether the following text contains PHI (Protected Health Information). Examples include: medical conditions, treatments, prescriptions, medical record numbers, etc.",
    }

    instruction = categories.get(category, categories["pii"])  # default to PII

    prompt_text = (
        f"{instruction}\n\n"
        f"Text to analyze:\n{text}\n\n"
        "Respond with:\n"
        "- 'yes' if sensitive data is present\n"
        "- 'no' if no sensitive data is present\n"
        "- A brief explanation describing why"
    )

    return GetPromptResult(
        description="A prompt for detecting sensitive data (PII/PCI/PHI).",
        messages=[
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": prompt_text
                }
            }
        ],
        metadata={"category": category}
    )




# -------------------------------------------------
# 🧠 ELICIT EXAMPLE (dynamic result)
# -------------------------------------------------

@mcp.tool()
def elicit_feedback(question: str) -> ElicitResult:
    """Ask the user a follow-up question"""
    return ElicitResult(
        action={
            "name": "feedback",
            "description": "Ask for user feedback"
        },
        content={"type": "text", "text": f"Can you share your thoughts on: {question}? Or should I add 2+3 instead??"}
    )

@mcp.tool()
def elicit_feedback2(question: str) -> ElicitResult:
    """Ask the user a follow-up question"""
    return ElicitResult(
        action="accept",  # must be one of 'accept', 'decline', or 'cancel'
        content={
            "type": "text",
            "text": f"Can you share your thoughts on: {question}? Or should I add 2+3 instead?"
        }
    )

# -------------------------------------------------
# 🚀 MAIN ENTRY POINT
# -------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=port)
