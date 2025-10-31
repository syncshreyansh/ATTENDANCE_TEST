# WhatsApp messaging service
import requests
import json
from config import Config

class WhatsAppService:
    def __init__(self):
        self.token = Config.WHATSAPP_TOKEN
        self.phone_id = Config.WHATSAPP_PHONE_ID
        self.base_url = f"https://graph.facebook.com/v17.0/{self.phone_id}/messages"

    def send_message(self, to_phone, message):
        """Send text message"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message}
        }
        try:
            response = requests.post(self.base_url, headers=headers, json=data)
            response.raise_for_status()
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"Error sending WhatsApp message: {e}")
            return False

    def send_template_message(self, to_phone, template_name, parameters):
        """Send template message"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "body",
                        "parameters": parameters
                    }
                ]
            }
        }
        try:
            response = requests.post(self.base_url, headers=headers, json=data)
            response.raise_for_status()
            return response.status_code == 200
        except requests.exceptions.RequestException as e:
            print(f"Error sending WhatsApp template message: {e}")
            return False

    def send_absence_alert(self, parent_phone, student_name, days_absent):
        """Send absence notification"""
        message = f"Alert: {student_name} has been absent for {days_absent} consecutive days. Please contact the school if needed."
        return self.send_message(parent_phone, message)

    def send_achievement_alert(self, parent_phone, student_name, achievement):
        """Send achievement notification"""
        message = f"Congratulations! {student_name} has achieved: {achievement}. Well done!"
        return self.send_message(parent_phone, message)