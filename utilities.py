import configparser


def read_config(config_file):
    """Read and parse the configuration file."""
    cfg = configparser.ConfigParser()
    cfg.read(config_file, encoding='utf-8')
    return cfg


def format_message(message):
    """Format the welcome and voice messages."""
    return message.replace(' | ', '\n')
