import os
import re
import sys

def is_likely_code(line_content):
    """
    Checks if a line (without the leading '#') looks like Python code.
    This is a heuristic.
    """
    # Common Python keywords
    keywords = [
        'def', 'class', 'if', 'else', 'elif', 'for', 'while', 'try', 'except',
        'finally', 'return', 'yield', 'import', 'from', 'with', 'as', 'assert',
        'async', 'await'
    ]
    # Common operators or structures
    operators_regex = r'[=\+\-\*\/%&\|\^\<\>\(\)\[\]\{\}:@\.,;\s]'

    # Remove extra spaces from the start of the content
    line_content = line_content.lstrip()

    if not line_content: # Empty line after '#'
        return False

    # Check for keywords
    for kw in keywords:
        if re.match(r"\b" + kw + r"\b", line_content):
            return True

    # Check for common code patterns (assignments, function calls, etc.)
    if re.search(r"=", line_content) and not line_content.strip().startswith("=="): # Assignment
        return True
    if re.search(r"\(.*\)", line_content) and not line_content.startswith("#"): # Function call like structure
        return True
    if re.search(r"\[.*\]", line_content): # List like structure
        return True
    if re.search(r"\{.*\}", line_content): # Dict/Set like structure
        return True
    if line_content.endswith(":") and not line_content.startswith("#"): # block statement
        return True

    # Check for significant use of operators or typical code punctuation
    # Count non-alphanumeric characters typical in code (excluding spaces)
    code_chars = len(re.findall(operators_regex, line_content))
    # If a significant portion of the line consists of these characters, it might be code
    if len(line_content) > 0 and (code_chars / len(line_content)) > 0.3:
        return True

    return False

def remove_commented_code(filepath, is_aggressive=False):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            original_lines = f.readlines()
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return False

    lines = list(original_lines) # Work on a copy
    new_lines = []
    idx = 0
    modified = False

    while idx < len(lines):
        line = lines[idx]
        stripped_line = line.lstrip() # Keep leading whitespace for indentation check

        if stripped_line.startswith('#'):
            potential_block_lines = []
            block_line_indices = []
            current_block_is_code_like = False

            # Start collecting a block of comments
            temp_idx = idx
            while temp_idx < len(lines) and lines[temp_idx].lstrip().startswith('#'):
                comment_content = lines[temp_idx].lstrip()[1:] # Content after '#'
                potential_block_lines.append(lines[temp_idx])
                block_line_indices.append(temp_idx)
                if is_likely_code(comment_content):
                    current_block_is_code_like = True
                temp_idx += 1

            # Evaluate the collected block
            # A "block" is more than 1 line, or if aggressive, even 1 line if it's code-like
            is_block = len(potential_block_lines) > 1

            if current_block_is_code_like and (is_block or is_aggressive):
                # It's a commented-out code block, skip it (i.e., don't add to new_lines)
                modified = True
                idx = temp_idx # Move past this block
            else:
                # It's a genuine comment block or single comment, keep it
                new_lines.extend(potential_block_lines)
                idx = temp_idx
        else:
            new_lines.append(line)
            idx += 1

    if modified:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"Cleaned commented code from {filepath}")
            return True
        except Exception as e:
            print(f"Error writing {filepath}: {e}", file=sys.stderr)
            # If writing fails, try to restore original content if possible (though complex)
            # For now, just report error.
            return False
    return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cleanup_comments.py <filepath1> [filepath2 ...]", file=sys.stderr)
        sys.exit(1)

    files_to_process = sys.argv[1:]
    settings_file_path = "bot/telegram_bot/handlers/settings.py"

    modified_files_count = 0

    for filepath in files_to_process:
        is_aggressive = (os.path.abspath(filepath) == os.path.abspath(settings_file_path))
        if os.path.isfile(filepath):
            if remove_commented_code(filepath, is_aggressive=is_aggressive):
                modified_files_count += 1
        else:
            print(f"File not found: {filepath}", file=sys.stderr)

    if modified_files_count > 0:
        print(f"\nTotal files modified by cleanup_comments.py: {modified_files_count}")
    else:
        print("\nNo files were modified by cleanup_comments.py.")
