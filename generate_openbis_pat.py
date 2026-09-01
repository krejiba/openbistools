from pybis import Openbis
from datetime import datetime
import configparser
import argparse
import warnings

# GLOBAL SETTINGS
BASE_URL = "https://openbis.imm.rwth-aachen.de"
ELN_URL = BASE_URL + "/openbis/webapp/eln-lims/"

# Suppress all warnings because we don't want to clutter the end-user's console
warnings.filterwarnings(action="ignore", category=FutureWarning)

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Get or create a personal access token for openBIS."
    )
    parser.add_argument(
        "--session-token",
        type=str,
        required=True,
        help=f"Your session token from openBIS ({ELN_URL})",
    )

    parser.add_argument("--debug", action="store_true")

    # Parse arguments
    args = parser.parse_args()

    # Use the session token provided by the user
    session_token = args.session_token

    # Initialize Openbis with the provided session token
    try:
        o = Openbis(url=BASE_URL, token=session_token)
    except ValueError as e:
        print(
            "\033[91m"
            + "This session token is no longer valid. Please provide a valid session token."
            + "\033[0m"
        )
        exit(1)

    usr = o._get_username()
    user = o.get_user(usr, only_data=True)
    firstname = user["firstName"].upper().replace("-", "")
    lastname = user["lastName"].upper().replace("-", "")

    # Get or create personal access tokenflag
    pat = o.get_or_create_personal_access_token(
        sessionName=f"{firstname + lastname}_{datetime.now().isoformat()[:7]}",
    )

    # Set up configuration parser to save details
    config = configparser.ConfigParser()
    config["openbis"] = {}
    config["openbis"]["openbis_endpoint"] = BASE_URL
    config["openbis"]["openbis_token"] = str(pat.permId)
    config["openbis"]["openbis_token_validity"] = str(pat.validFromDate)[:7]
    config["openbis"]["openbis_session_name"] = str(pat.sessionName)

    # Save configuration to file (optional)
    with open("./openbis_config.ini", "w") as configfile:
        config.write(configfile)

    if args.debug:
        df = o.get_personal_access_tokens().df[["permId", "sessionName", "validToDate"]]
        print(df)
        print("Latest PAT: ", df["permId"].tail(1).values[0])

    print("\033[92m" + "Configuration saved to openbis_config.ini" + "\033[0m")
    print("\033[92m" + "PAT: " + str(pat.permId) + "\033[0m")
