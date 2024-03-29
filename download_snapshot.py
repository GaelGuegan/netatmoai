import time
import logging
import json
import sys
from os import getenv
from os.path import expanduser
import urllib.parse, urllib.request
from datetime import datetime, timedelta
import io
import pytimeparse
from ultralytics import YOLO
import PIL.Image as Image

PYTHON3 = (sys.version_info.major > 2)
if not PYTHON3 :
    raise Exception('Python version need to be > 3 (current = {sys.version}')

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
        resp = urllib.request.urlopen(req, params, timeout=timeout)
    else:
        resp = urllib.request.urlopen(req, timeout=timeout)

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
        if self.expiration < time.time() :
            self.renew_token()
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


class ModulesEvents():
    """ Get last modules events
    """
    _URL_GET_EVENTS = _URL_BASE + 'api/getevents'

    def __init__(self, auth_data, home_id, size=300):
        self.raw_data = []
        post_params = {
            "access_token" : auth_data.access_token,
            "home_id": home_id,
            "size": size
        }
        self.auth_data = auth_data
        self.home_id = home_id
        self.size = size
        resp = post_request(self._URL_GET_EVENTS, post_params)
        self.raw_data = resp['body']['home']['events']

        if not self.raw_data:
            # pylint: disable-next=broad-exception-raised
            raise Exception('No home found')

    def get_events_from_type(self, module_type='NOC'):
        """ Get events from a type
        """
        post_params = {
            "access_token" : self.auth_data.access_token,
            "home_id": self.home_id,
            "device_types": module_type,
            "size": self.size
        }
        return post_request(self._URL_GET_EVENTS, post_params)['body']['home']['events']

    def get_snapshots_url(self, module_type='NOC', since=None, _from=None, to=None):
        """ Get Snapshots URL in a JSON format:
        [{'timestamp': xxxx, 'url': xxxx}, {'timestamp': xxxx, 'url': xxxx}]
        """
        snapshots_url = []
        since_timestamp = sys.maxsize

        if since:
            since_timestamp = pytimeparse.parse(since)
            since_timestamp = (datetime.now() - timedelta(seconds=since_timestamp)).timestamp()
            _from = None
            to = None

        if _from:
            from_timestamp = datetime.fromisoformat(_from).timestamp()
        if to:
            to_timestamp = datetime.fromisoformat(to).timestamp()
        if to_timestamp < from_timestamp:
            raise AssertionError(f'from date ({_from}) cannot be greater than to date ({to})')

        for event in self.get_events_from_type(module_type):
            if event['time'] > since_timestamp or to_timestamp > event['time'] > from_timestamp:
                for subevent in event.get('subevents', []):
                    url = subevent['snapshot'].get('url', None)
                    timestamp = subevent['time']
                    if url:
                        snapshots_url.append({'timestamp': timestamp, 'url': url})

        return snapshots_url

if __name__ == "__main__":

    # Init Netatmo Requests Objects
    auth = ClientAuth()
    home_id = HomesData(auth).get_homes_id(name='Kergal')
    status = HomeStatus(auth, home_id)
    events = ModulesEvents(auth, home_id, size=300)

    # Load predection model YOLO
    yolo_model = YOLO('yolov8n.pt')
    yolo_model_names = {v: k for k, v in yolo_model.model.names.items()}
    logging.warning('Model yolov8n.pt can detect the following object: %s', yolo_model.model.names)

    # Retrieve URL Snapshots
    noc_events_url = events.get_snapshots_url(_from='2023-12-15', to='2024-01-05')
    for url in noc_events_url:
        # Download snapshot in RAM
        jpeg_image = post_request(url['url'])
        image = Image.open(io.BytesIO(jpeg_image))

        # Save prediction in File
        results = yolo_model.predict(image, classes=yolo_model_names['person'], verbose=False)[0]
        filename_time = datetime.fromtimestamp(url['timestamp'])
        filename_time = filename_time.strftime('%Y%m%d_%Hh%Mm%Ss')
        results.save_crop(save_dir='.', file_name=filename_time)
