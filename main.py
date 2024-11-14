from typing import Dict, List, Optional
import logging
from flask import Flask, request, render_template
import requests
from discord_webhook import DiscordWebhook, DiscordEmbed

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants
STATUS_COLORS: Dict[str, str] = {
    'Success': '7CFC00',
    'Unknown': '909090',
    'Warning': 'FFBF00',
    'Error': 'FF0000',
    'FATAL': 'FF0000'
}

STATUS_ICONS: Dict[str, str] = {
    'Success': ':white_check_mark:',
    'Warning': ':warning:',
    'Error': ':no_entry:',
    'Unknown': ':grey_question:',
    'FATAL': ':fire:'
}

DUPLICATI_DATA_ITEMS: List[str] = [
    'DeletedFiles', 'DeletedFolders', 'ModifiedFiles', 'ExaminedFiles',
    'OpenedFiles', 'AddedFiles', 'SizeOfModifiedFiles', 'SizeOfAddedFiles',
    'SizeOfExaminedFiles', 'SizeOfOpenedFiles', 'NotProcessedFiles',
    'AddedFolders', 'TooLargeFiles', 'FilesWithError', 'ModifiedFolders',
    'ModifiedSymlinks', 'AddedSymlinks', 'DeletedSymlinks', 'PartialBackup',
    'Dryrun', 'MainOperation', 'ParsedResult', 'Version', 'EndTime',
    'BeginTime', 'Duration', 'MessagesActualLength', 'WarningsActualLength',
    'ErrorsActualLength'
]

app = Flask(__name__)

def format_file_size(size_bytes: int, suffix: str = "B") -> str:
    """Convert bytes to human readable format."""
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:3.1f}{unit}{suffix}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f}Yi{suffix}"

def format_duration(duration_parts: List[str]) -> str:
    """Format duration string from HH:MM:SS format."""
    duration = ""
    hours, minutes, seconds = duration_parts
    
    if hours != "00":
        duration += f"{hours} Hrs "
    if minutes != "00":
        duration += f"{minutes} Mins "
    if seconds != "00":
        seconds_formatted = int(round(float(seconds), 1))
        duration += f"{seconds_formatted} Secs "
    
    return duration.strip()

def parse_duplicati_message(message: str) -> tuple[Dict[str, str], str]:
    """Parse Duplicati message and extract data items and errors."""
    output = {}
    errors = []
    
    for line in message.split('\n'):
        if line.startswith(tuple(DUPLICATI_DATA_ITEMS)):
            if ':' in line:
                key, value = line.split(': ', 1)
                output[key] = value
        elif 'Access to the path' in line:
            error = line.split('Access to the path ')
            errors.append(error[1])
    
    errors = list(dict.fromkeys(errors))  # Remove duplicates
    error_output = '\n'.join(f' Access to path {e}' for e in errors[:2])
    
    return output, error_output

def create_discord_embed(data: Dict[str, str], name: str, error_output: str) -> DiscordEmbed:
    """Create Discord embed with backup information."""
    status = data["ParsedResult"]
    title = f'{STATUS_ICONS[status]} Duplicati job {name} {data["MainOperation"]} {status} {STATUS_ICONS[status]}'
    
    embed = DiscordEmbed(
        title=title,
        color=STATUS_COLORS[status],
        description=error_output
    )
    
    # Set author and footer
    embed.set_author(
        name="Duplicati Discord Notification",
        url="https://duplicati-notifications.lloyd.ws/"
    )
    embed.set_footer(text=f'{data["MainOperation"]} {status}')
    
    # Format begin time
    begin_time = data["BeginTime"].split('(')[0]
    
    # Format duration
    duration = format_duration(data["Duration"].split(':'))
    
    # Add fields
    fields = [
        ('Started', begin_time),
        ('Time Taken', duration),
        ('No. Files', '{:,}'.format(int(data["ExaminedFiles"]))),
        ('Added Files', '{:,}'.format(int(data["AddedFiles"]))),
        ('Added Size', format_file_size(int(data["SizeOfAddedFiles"]))),
        ('Deleted Files', '{:,}'.format(int(data["DeletedFiles"]))),
        ('Modified Files', '{:,}'.format(int(data["ModifiedFiles"]))),
        ('Modified Size', format_file_size(int(data["SizeOfModifiedFiles"]))),
        ('Size', format_file_size(int(data["SizeOfExaminedFiles"])))
    ]
    
    for name, value in fields:
        embed.add_embed_field(name=name, value=value)
    
    return embed

@app.route("/")
def home():
    return render_template('index.html')

@app.route("/report", methods=['POST'])
def report():
    webhook_url = request.args.get('webhook')
    if not webhook_url:
        logger.warning("Received report request without webhook URL")
        return '{}'
    
    message = request.form.get('message')
    name = request.args.get('name')
    
    if name:
        logger.info(f"Processing backup report for job: {name}")
        
        # Process Discord webhook
        try:
            data, error_output = parse_duplicati_message(message)
            
            webhook = DiscordWebhook(
                url=webhook_url,
                username=f'{data["MainOperation"]} Notification'
            )
            
            embed = create_discord_embed(data, name, error_output)
            webhook.add_embed(embed)
            response = webhook.execute()
            
            logger.info(
                f"Backup report sent to Discord - Job: {name} "
                f"Status: {data['ParsedResult']} "
                f"Operation: {data['MainOperation']} "
                f"Files: {data['ExaminedFiles']} "
                f"Size: {format_file_size(int(data['SizeOfExaminedFiles']))}"
            )
            
            if error_output:
                logger.warning(f"Backup completed with errors - Job: {name}\n{error_output}")
                
        except Exception as e:
            logger.error(f"Error processing Discord notification for job {name}: {str(e)}")
            return '{}'
    
    # Forward to Duplicati monitor if URL provided
    duplicati_monitor_url = request.args.get('duplicatimonitor')
    if duplicati_monitor_url:
        try:
            logger.info(f"Forwarding report to Duplicati monitor: {duplicati_monitor_url}")
            response = requests.post(duplicati_monitor_url, data={'message': message})
            response.raise_for_status()
            logger.info("Successfully forwarded report to Duplicati monitor")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error forwarding to Duplicati monitor: {str(e)}")
    
    return '{}'

if __name__ == "__main__":
    logger.info("Starting Duplicati Discord Notification Service...")
    app.run(host="0.0.0.0")
    