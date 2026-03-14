import questionary

def main_menu():
    
    return questionary.select(
        "Select an action to proceed!",
        choices = [
            "Create User",
            "Choose News Channels",
            "Choose Interests",
            "Set Email Delivery Frequency",
            "Stop Email Delivery",
            "Resume Email Delivery",
            "Generate Email Now",
            "Exit"
        ]
    ).ask()
    
def channel_menu(default = None):
    return questionary.checkbox(
        "Select News Channels",
        choices=[
            "Global",
            "Local",
            "Investment",
            "Interested Topics"
        ],
        default = default
    ).ask()
    
def frequency_menu():
    
    return questionary.select(
        "Choose Email Delivery Frequency",
        choices = [
            "Immediate",
            "Daily",
            "Weekly",
            "Monthly",
            "Three Months",
            "Six Months",
            "Yearly",
            "None"
            
        ]
    ).ask()       
