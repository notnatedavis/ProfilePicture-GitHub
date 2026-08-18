#   src/logging_config.py

# --- Imports ---
import logging

# --- Formatting constants ---
# o   logger_name : message
LOG_FORMAT = "o   %(name)s : %(message)s"
CONTINUATION_INDENT = "        "

def configure_logging(level=logging.INFO) :
    # configure the root logger to use the compact bullet format
    logging.basicConfig(level=level, format=LOG_FORMAT)

def block(message) :
    # render a message that should appear on its own indented line
    # o   __main__ : 
    #         Starting profile picture update
    return f"\n{CONTINUATION_INDENT}{message}"

def label_value(label, value, separator=" : ") :
    # render a label/value pair where the value is placed on the next
    # o   image_selector : Selected Pinterest image : 
    #         https://...
    return f"{label}{separator}\n{CONTINUATION_INDENT}{value}"