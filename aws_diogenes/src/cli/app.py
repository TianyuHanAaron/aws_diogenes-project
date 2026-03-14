import questionary

try:
    from ..main import run_with_user_request
except ImportError:
    from main import run_with_user_request

from .profiles import load_profiles, save_profiles, find_user
from .menus import main_menu, channel_menu, frequency_menu
from .nova_suggestions import suggests_channels


def _save_user(updated_user):
    profiles = load_profiles()
    for index, profile in enumerate(profiles):
        if profile["user_id"] == updated_user["user_id"]:
            profiles[index] = updated_user
            save_profiles(profiles)
            return
    profiles.append(updated_user)
    save_profiles(profiles)


def create_user():
    
    user_id = questionary.text("User ID").ask()
    email = questionary.text("Email").ask()
    location = questionary.text("City").ask()
    
    profiles = load_profiles()
    profile = {
        "user_id": user_id,
        "email": email,
        "location": location,
        "channels": [],
        "interests": [],
        "delivery_frequency": "weekly",
        "email_enabled": True
    }
    
    profiles.append(profile)
    
    save_profiles(profiles)
    
    print("User Created")
    
def choose_interests():
    user_id = questionary.text("User ID").ask()
    user = find_user(user_id)
    
    if not user:
        print("User not found")
        return
    interests = questionary.text(
        """Enter something you find interesting, \n
        Separated by comma
        
        """
    ).ask()
    
    interests_list = [i.strip() for i in interests.split(",")]
    
    user["interests"] = interests_list
    _save_user(user)
    
    print("Interests recorded")
    
def choose_news_channels():
    user_id = questionary.text("User ID").ask()
    user = find_user(user_id)
    
    if not user:
        print("User Not Found")
        return
    interests = user.get("interests", [])
    
    suggested = []
    
    if interests:
        suggested = suggests_channels(interests)
        print(f"Suggested channels based on interests: {suggested}")
        
    channels = channel_menu(default=suggested)
    user["channels"] = channels
    _save_user(user)
    print("Channel Updated")

def set_frequency():
    user_id = questionary.text("User ID").ask()
    
    user = find_user(user_id)
    
    if not user:
        print("User not found")
        return
    freq = frequency_menu()
    
    user["delivery_frequency"] = freq
    _save_user(user)
    
    print("frequency updated")
    
def stop_email():
    user_id = questionary.text("User ID").ask()
    
    user = find_user(user_id)
    
    if not user:
        print("User not Found")
        return
    
    user["email_enabled"] = False
    _save_user(user)
    
    print("email delivery suspended")
    
def resume_email():
    user_id = questionary.text("User ID").ask()
    
    user = find_user(user_id)
    
    if not user:
        print ("User Not Found")
        return
    user["email_enabled"] = True
    _save_user(user)
    
    print("Email Delivery Resumed")
    
def generate_email_digest():
    user_id = questionary.text("User ID").ask()
    
    user = find_user(user_id)
    
    if not user:
        print("User Not Found")
        return
    if not user.get("email_enabled", True):
        print("Email Delivery Services Disabled For This User")
        return
    
    run_with_user_request(user)
    
    print("Digest generation started")
    
def run_cli():
    while True:
        action = main_menu()
        
        if action == "Create User":
            create_user()
        elif action == "Choose News Channels":
            choose_news_channels()
        elif action == "Choose Interests":
            choose_interests()
        elif action == "Set Email Delivery Frequency":
            set_frequency()
        elif action == "Stop Email Delivery":
            stop_email()
        elif action == "Resume Email Delivery":
            resume_email()
        elif action == "Generate Email Now":
            generate_email_digest()
        elif action == "Exit":
            break
        
if __name__ == "__main__":
    run_cli()
