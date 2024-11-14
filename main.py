from flask import Flask, request, render_template
import requests
from discord_webhook import DiscordWebhook, DiscordEmbed
import logging
from typing import Dict, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Constants organized by purpose
BACKUP_STATUS = {
    'colors': {
        'Success': '7CFC00',
        'Unknown': '909090',
        'Warning': 'FFBF00',
        'Error': 'FF0000',
        'FATAL': 'FF0000'
    },
    'icons': {
        'Success': ':white_check_mark:',
        'Warning': ':warning:',
        'Error': ':no_entry:',
        'Unknown': ':grey_question:',
        'FATAL': ':fire:'
    }
}

DUPLICATI_DATA_ITEMS = [
    # Backup Statistics
    'DeletedFiles', 'DeletedFolders', 'ModifiedFiles', 'ExaminedFiles',
    'OpenedFiles', 'AddedFiles', 'NotProcessedFiles', 'FilesWithError',
    'AddedFolders', 'TooLargeFiles',
    
    # Size Information
    'SizeOfModifiedFiles', 'SizeOfAddedFiles', 'SizeOfExaminedFiles',
    'SizeOfOpenedFiles',
    
    # Symlink Operations
    'ModifiedSymlinks', 'AddedSymlinks', 'DeletedSymlinks',
    
    # Operation Details
    'PartialBackup', 'Dryrun', 'MainOperation', 'ParsedResult',
    
    # Timing Information
    'Version', 'EndTime', 'BeginTime', 'Duration',
    
    # Message Counts
    'MessagesActualLength', 'WarningsActualLength', 'ErrorsActualLength'
]

def format_file_size(num: int, suffix: str = "B") -> str:
    """
    Format a file size into human readable format.
    Args:
        num: Size in bytes
        suffix: Unit suffix (default: "B")
    Returns:
        Formatted string like "1.5GiB"
    """
    num = int(num)
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def format_duration(duration_parts: list[str]) -> str:
    """
    Format duration from parts into human readable string.
    Args:
        duration_parts: List of ["HH", "MM", "SS.ms"]
    Returns:
        Formatted string like "1 Hr 30 Mins 45 Secs"
    """
    duration = ""
    if duration_parts[0] != '00':
        duration = f"{duration} {duration_parts[0]} Hrs "
    if duration_parts[1] != '00':
        duration = f"{duration} {duration_parts[1]} Mins "
    if duration_parts[2] != '00':
        seconds = int(round(float(duration_parts[2]), 1))
        duration = f"{duration} {seconds} Secs "
    return duration.strip()

def parse_duplicati_message(message: str) -> Tuple[Dict[str, str], str]:
    """
    Parse the Duplicati backup message into data and error output.
    
    Args:
        message: Raw message string from Duplicati
        
    Returns:
        Tuple of (parsed data dict, formatted error string)
    """
    output = {}
    errors = []
    
    for line in message.split('\n'):
        if line.startswith(tuple(DUPLICATI_DATA_ITEMS)):
            if ':' in line:
                key, value = line.split(': ', 1)
                output[key] = value
                logger.debug(f"Parsed data item: {key}")
        elif 'Access to the path' in line:
            error = line.split('Access to the path ')
            errors.append(error[1])
            logger.warning(f"Found error: Access to path {error[1]}")
    
    errors = list(dict.fromkeys(errors))  # Remove duplicates
    error_output = '\n'.join(f' Access to path {e}' for e in errors[:2])
    
    # Process duration and begin time
    output['Duration'] = output['Duration'].split(':')
    output['BeginTime'] = output['BeginTime'].split('(')[0]
    
    return output, error_output

def create_discord_embed(data: Dict[str, str], name: str, error_output: str) -> DiscordEmbed:
    """
    Create a Discord embed with the backup information in a cleaner format.
    
    Args:
        data: Parsed backup data
        name: Backup job name
        error_output: Formatted error string
        
    Returns:
        Configured DiscordEmbed object
    """
    status = data["ParsedResult"]
    operation = data["MainOperation"]
    
    # Create a cleaner title
    status_icon = BACKUP_STATUS["icons"][status]
    title = f"{status_icon} {name} - {operation}"
    
    # Select color based on status
    embed = DiscordEmbed(
        title=title,
        color=BACKUP_STATUS["colors"][status],
    )
    
    embed.set_author(
        name="Duplicati Backup Report",
        url="https://duplicati-notifications.lloyd.ws/"
    )
    
    # Status and Timing Information
    time_info = (
        f"**Started:** {data['BeginTime']}\n"
        f"**Duration:** {format_duration(data['Duration'])}"
    )
    embed.add_embed_field(
        name="⏱️ Timing",
        value=time_info,
        inline=False
    )
    
    # File Statistics
    processed_files = int(data["ExaminedFiles"])
    modified_files = int(data["ModifiedFiles"])
    added_files = int(data["AddedFiles"])
    deleted_files = int(data["DeletedFiles"])
    total_changes = modified_files + added_files + deleted_files
    
    # Only show stats that have non-zero values
    stats = []
    if added_files:
        stats.append(f"📄 **Added:** {added_files:,} ({format_file_size(int(data['SizeOfAddedFiles']))})")
    if modified_files:
        stats.append(f"📝 **Modified:** {modified_files:,} ({format_file_size(int(data['SizeOfModifiedFiles']))})")
    if deleted_files:
        stats.append(f"🗑️ **Deleted:** {deleted_files:,}")
    
    if stats:
        embed.add_embed_field(
            name=f"📊 Changes ({total_changes:,} of {processed_files:,} files)",
            value="\n".join(stats),
            inline=False
        )
    else:
        embed.add_embed_field(
            name="📊 Statistics",
            value=f"No changes in {processed_files:,} files",
            inline=False
        )
    
    # Total Size
    embed.add_embed_field(
        name="💾 Total Size",
        value=format_file_size(int(data["SizeOfExaminedFiles"])),
        inline=False
    )
    
    # Add errors if present
    if error_output:
        embed.add_embed_field(
            name="⚠️ Errors",
            value=f"```{error_output}```",
            inline=False
        )
    
    # Set a more informative footer
    timestamp = data['BeginTime'].strip()
    footer_text = (
        f"{operation} {status} • {timestamp}"
    )
    embed.set_footer(text=footer_text)
    
    return embed

app = Flask(__name__)

@app.route("/")
def home():
    return render_template('index.html')

@app.route("/report", methods=['POST'])
def report():
    logger.info("Received report request")
    
    webhook_url = request.args.get('webhook')
    if not webhook_url:
        logger.warning("No webhook URL provided")
        return '{}'
    
    logger.info(f"Webhook URL present: {webhook_url[:20]}...")
    message = request.form.get('message')
    logger.info("Got message from form data")
    
    name = request.args.get('name')
    if name:
        logger.info(f"Processing backup for job: {name}")
        
        # Parse message and create Discord notification
        try:
            data, error_output = parse_duplicati_message(message)
            
            webhook = DiscordWebhook(
                url=webhook_url,
                username=f'{data["MainOperation"]} Notification'
            )
            
            embed = create_discord_embed(data, name, error_output)
            webhook.add_embed(embed)
            
            logger.info(f"Sending Discord webhook for job {name}")
            response = webhook.execute()
            logger.info("Discord webhook sent successfully")
            
        except Exception as e:
            logger.error(f"Error processing Discord notification: {str(e)}")
    
    # Forward to Duplicati monitor if configured
    duplicati_monitor_url = request.args.get('duplicatimonitor')
    if duplicati_monitor_url:
        logger.info("Forwarding to Duplicati monitor")
        try:
            response = requests.post(
                duplicati_monitor_url,
                data={'message': message}
            )
            logger.info("Successfully forwarded to Duplicati monitor")
        except Exception as e:
            logger.error(f"Error forwarding to Duplicati monitor: {str(e)}")
    
    return '{}'

if __name__ == "__main__":
    logger.info("Starting Duplicati Discord Notification Service...")
    app.run(host="0.0.0.0")
