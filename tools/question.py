import json
from typing import List, Optional, Callable
from utils.schema_helper import tool

@tool
def question_tool(questions: List[str], ask_callback: Optional[Callable[[List[str]], List[str]]] = None) -> str:
    """
    Asks the user questions to gather additional information or clarification.
    Returns a JSON string containing the formatted answers.
    
    USAGE RULES:
    1. Use this tool when you are stuck, need a decision made, or require more context.
    2. The agent execution will typically pause after this tool is called to wait for the user's response.
    3. Do not use this tool for rhetorical questions; only use it when you expect an answer.
    
    :param questions: A list of question strings to ask the user.
    :param ask_callback: Optional callback function to handle the UI/CLI interaction. 
                         If not provided, defaults to standard terminal input.
    """
    # 1. Prepare the structure
    result = {
        "title": "",
        "output": "",
        "answers": [],
        "error": None
    }

    # 2. Validation
    if not questions:
        result["error"] = "Provide at least one question to ask."
        return json.dumps(result)

    # 3. Execution (Asking the questions)
    try:
        answers = []
        if ask_callback:
            # If integrated into a larger UI/system, use the provided callback
            answers = ask_callback(questions)
        else:
            # Fallback to standard CLI input for local execution
            print("\n[Agent needs input]")
            for q in questions:
                ans = input(f"{q}\n> ")
                answers.append(ans.strip())
            print("[Input received]\n")

        # 4. Format the output to match the original TypeScript logic
        formatted_pairs = []
        for i, q in enumerate(questions):
            ans = answers[i] if i < len(answers) and answers[i] else "Unanswered"
            # Format: "Question?"="Answer"
            formatted_pairs.append(f'"{q}"="{ans}"')
        
        formatted_string = ", ".join(formatted_pairs)

        result["title"] = f"Asked {len(questions)} question{'s' if len(questions) > 1 else ''}"
        result["output"] = f"User has answered your questions: {formatted_string}. You can now continue with the user's answers in mind."
        result["answers"] = answers

    except Exception as e:
        result["error"] = f"Error gathering user input: {str(e)}"

    # 5. Return JSON String
    return json.dumps(result)