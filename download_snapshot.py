import time
import logging
import urllib.parse, urllib.request
from os import getenv
from os.path import expanduser
import json
import requests
import wget

######################## AUTHENTICATION INFORMATION ######################
# To be able to have a program accessing your netatmo data, you have to register your program as
# a Netatmo app in your Netatmo account. All you have to do is to give it a name (whatever) and you will be
# returned a client_id and secret that your app has to supply to access netatmo servers.
# Authentication:
#  1 - The .netatmo.credentials file in JSON format in your home directory (now mandatory for regular use)
#  2 - Values defined in environment variables : CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
# Note that the refresh token being short lived, using envvar will be restricted to speific testing use case
# Note: this file will be rewritten by the library to record refresh_token change
# If you run your application in container, remember to persist this file
CREDENTIALS = expanduser(".netatmo_credentials")
with open(CREDENTIALS, 'r', encoding='utf-8') as file:
    cred = {k.upper():v for k,v in json.loads(file.read()).items()}

def getParameter(key, default):
    return getenv(key, default.get(key, None))

# Override values with content of env variables if defined
_CLIENT_ID     = getParameter("CLIENT_ID", cred)
_CLIENT_SECRET = getParameter("CLIENT_SECRET", cred)
_REFRESH_TOKEN = getParameter("REFRESH_TOKEN", cred)

_URL_BASE = 'https://api.netatmo.com/'
_URL_GET_EVENTS = _URL_BASE + 'getevents'


def post_request(url, params=None, timeout=10):
    """ Post request with authentication
    Return raw data if image.
    Else return json response.
    """
    data = b""
    req = urllib.request.Request(url)
    if params:
        req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
        if "access_token" in params:
            req.add_header("Authorization", f'Bearer {params.pop("access_token")}')
        params = urllib.parse.urlencode(params).encode('utf-8')
        resp = urllib.request.urlopen(req, params, timeout=timeout) if params else urllib.request.urlopen(req, timeout=timeout)

    for buff in iter(lambda: resp.read(65535), b''):
        data += buff

    # Return values in bytes if not json data to handle properly camera images
    returned_content_type = resp.getheader("Content-Type")
    if "application/json" in returned_content_type:
        return json.loads(data.decode("utf-8"))
    else:
        return data


class ClientAuth:
    """
    Request authentication and keep access token available through token method.
    Renew it automatically if necessary.

    Args:
        clientId (str): Application clientId delivered by Netatmo on dev.netatmo.com
        client_secret (str): Application Secret key delivered by Netatmo on dev.netatmo.com
        refresh_token (str) : Scoped refresh token
        """
    _URL_AUTH = _URL_BASE + 'oauth2/token'

    def __init__(self, client_id=_CLIENT_ID,
                       client_secret=_CLIENT_SECRET,
                       refresh_token=_REFRESH_TOKEN):

        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token = None
        self.refresh_token = refresh_token
        self.expiration = 0 # Force refresh token

    @property
    def access_token(self):
        ''' Access token '''
        if self.expiration < time.time() : self.renew_token()
        return self._access_token

    def renew_token(self):
        ''' Renew token '''
        post_params = {
                "grant_type" : "refresh_token",
                "refresh_token" : self.refresh_token,
                "client_id" : self._client_id,
                "client_secret" : self._client_secret
                }
        resp = post_request(self._URL_AUTH, post_params)
        if self.refresh_token != resp['refresh_token']:
            self.refresh_token = resp['refresh_token']
            cred["REFRESH_TOKEN"] = self.refresh_token
            with open(CREDENTIALS, "w", encoding='utf-8') as file:
                file.write(json.dumps(cred, indent=True))
        self._access_token = resp['access_token']
        self.expiration = int(resp['expire_in'] + time.time())

class HomeStatus:
    """
        Class managing general status of home devices
    """
    _URL_HOME_STATUS = _URL_BASE + 'api/homestatus'

    def __init__(self, auth_data, home_id):
        post_params = {
                "access_token" : auth_data.access_token,
                "home_id": home_id
                }
        self.resp = post_request(self._URL_HOME_STATUS, post_params)
        self.raw_data = self.resp['body']['home']
        if not self.raw_data:
            # pylint: disable-next=broad-exception-raised
            raise Exception(f'No home {home_id} found')
        self.rooms = self.raw_data.get('rooms')
        if not self.rooms:
            logging.warning('No rooms defined')
        self.modules = self.raw_data['modules']

    def get_modules_id(self, module_type=None):
        ''' Get modules ID '''
        # return all modules
        if not module_type:
            return [module['id'] for module in self.modules]
        # return only modules with correspond type
        return [module['id'] for module in self.modules if module['type'] == module_type]


class HomesData:
    """
        Class managing data of homes
    """
    _URL_HOMES_DATA = _URL_BASE + 'api/homesdata'

    def __init__(self, auth_data):
        post_params = {
                "access_token" : auth_data.access_token,
                }
        self.resp = post_request(self._URL_HOMES_DATA, post_params)
        self.raw_data = self.resp['body']['homes']
        if not self.raw_data:
            # pylint: disable-next=broad-exception-raised
            raise Exception('No home found')

    def get_homes_id(self, name=None):
        ''' Get homes ID '''
        # return all modules
        if not name:
            return [home['id'] for home in self.raw_data]
        # return only modules with correspond type
        return [home['id'] for home in self.raw_data if home['name'] == name][0]

# Save Image from NOC events to dist
def download_snapshot(number=1, mac="70:ee:50:95:d5:1c"):
    """ Download snapshot from events
    """
    events = requests.get(_URL_GET_EVENTS + "?home_id=" + home_id + "&size=" + str(number), headers=headers)
    events = json.loads(events.content)

    for event in events["body"]["home"]["events"]:
        if event["module_id"] == mac:
            url = event["subevents"][0]["snapshot"]["url"]
            wget.download(url)


if __name__ == "__main__":
    auth = ClientAuth()
    home_id = HomesData(auth).get_homes_id(name='Kergal')
    status = HomeStatus(auth, home_id)
    print(status.raw_data)
