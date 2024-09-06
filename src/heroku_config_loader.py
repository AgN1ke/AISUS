import configparser
import subprocess

def load_config(file_path):
    """Load configuration from a file."""
    config = configparser.ConfigParser()
    try:
        with open(file_path, 'r', encoding='utf-8') as configfile:
            config.read_file(configfile)
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
        exit(1)
    except Exception as e:
        print(f"Error: Could not read the file {file_path}. Error: {str(e)}")
        exit(1)
    return config

def set_heroku_config(config, app_name):
    """Set Heroku environment variables using Heroku CLI."""
    for section in config.sections():
        for key, value in config.items(section):
            env_var_name = f"{section.upper()}_{key.upper()}"
            value = value.replace("'", "\\'")  # Escape single quotes in value
            command = f"heroku config:set {env_var_name}='{value}' --app {app_name}"
            try:
                result = subprocess.run(command, check=True, shell=True, text=True, capture_output=True)
                print(f"Success setting {env_var_name}: {result.stdout}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to set {env_var_name}: {e.stderr}")

def main():
    config_file_path = '../configs/config.ini'  # Update the path to your config file
    app_name = 'tranquil-thicket-16349'  # Correct Heroku app name
    config = load_config(config_file_path)
    set_heroku_config(config, app_name)

if __name__ == "__main__":
    main()
