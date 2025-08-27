import sys
import inquirer

def safe_prompt(questions):
    """
        Wrapper around inquirer.prompt that exits immediately on Ctrl+C.

        Parameters:
            questions (list): A list of dictionaries representing the questions to be asked using inquirer.prompt(). Each dictionary should have a 'type' key specifying the type of input to expect, and other keys specific to the type of input.

        Returns:
            dict: A dictionary containing the answers to the questions. If the user cancels the prompt, returns None.
    """
    try:
        answers = inquirer.prompt(questions)
        if answers is None:
            sys.exit(1)  # Ensure exit if the user cancels
        return answers
    except KeyboardInterrupt:
        print("\nOperation cancelled. Exiting.")
        sys.exit(1)  # Exit immediately