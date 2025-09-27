import requests
import json
import pandas as pd

# API Headers
headers ={'accept': 'application/json', 'X-APISETU-CLIENTID': 'in.gov.up.srlm', 'X-APISETU-APIKEY': 'c0f33882283486f250bd031393c966f042bcc20eaaee62dbac860a7edba96b5f'}

# District Data building
district_url = 'https://cdn.lokos.in/lokos-masterdata/state/29.json'
district_response = (requests.get(district_url, headers=headers)).json()
district_data = {key: [d.get(key) for d in district_response] for key in district_response[0].keys()}
# print(json.dumps(district_data, indent=2, ensure_ascii=False))

# Block Data building
district_ids = district_data.get('district_id')
# for d_id in district_ids:
#     block_url = f'https://cdn.lokos.in/lokos-masterdata/state/29/district/{d_id}.json'
#     block_response = (requests.get(block_url, headers=headers)).json()
#     block_data = {key: [b.get(key) for b in block_response] for key in block_response[0].keys()}

# # Excel Creator
# df = pd.DataFrame(block_data)
# df.to_excel("blocks_from_api.xlsx", index=False)

# print("Done scene!")