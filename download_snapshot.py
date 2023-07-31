import requests
import json
import wget

url_api = "https://api.netatmo.com/api"      
home_id="63b2b940dfc55930790cfd43"
auth_token = "xxxxx|xxxxxx"  
headers = {                              
            'Authorization': 'Bearer ' + auth_token,                           
            'Content-Type': 'application/json'   
          }          
mac_cabane = "70:ee:50:95:d5:1c"

# Get Home General Status   
homestatus = requests.get(url_api + "/homestatus?" + "home_id=" + home_id, headers=headers)
homestatus = json.loads(homestatus.content)

# Get Outdoor URL  
noc_vpn_url = None                                                                                                      
for modules in homestatus["body"]["home"]["modules"]:                                                                       
    if modules["type"] == "NOC":                                                                                                
        noc_vpn_url = modules["vpn_url"]

# Save Image from NOC events to dist                                                                                    
def download_snapshot(number=1, mac="70:ee:50:95:d5:1c"):    
    events = requests.get(url_api + "/getevents?" + "home_id=" + home_id + "&size=" + str(number), headers=headers)
    events = json.loads(events.content)                                                                                           

    for event in events["body"]["home"]["events"]:       
         if event["module_id"] == mac:                                           
             url = event["subevents"][0]["snapshot"]["url"]              
             wget.download(url)   
