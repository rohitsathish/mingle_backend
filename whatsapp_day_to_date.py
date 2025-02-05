#%%
from datetime import datetime, timedelta
from typing import Dict, Optional

def get_whatsapp_date_mapping() -> Dict[str, datetime.date]:
	"""
	Creates a mapping between WhatsApp day references and actual dates.

	Returns:
		Dict[str, datetime.date]: Mapping of WhatsApp day references to actual dates
	"""
	today = datetime.today()
	mapping = {
		"TODAY": today.date(),
		"YESTERDAY": (today - timedelta(days=1)).date()
	}

	# Map weekday names
	weekdays = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
	for i, day in enumerate(weekdays):
		if today.weekday() < i:
			mapping[day] = today.date() + timedelta(days=i - today.weekday() - 7)
		else:
			mapping[day] = today.date() + timedelta(days=i - today.weekday())

	return mapping

def convert_whatsapp_date(date_text: str) -> Optional[datetime.date]:
	"""
	Converts WhatsApp date text to actual date object.

	Args:
		date_text (str): Date text from WhatsApp (e.g., "TODAY", "YESTERDAY", "DD/MM/YYYY")

	Returns:
		Optional[datetime.date]: Converted date or None if conversion fails
	"""
	try:
		date_text = date_text.strip().upper()
		mapping = get_whatsapp_date_mapping()

		if date_text in mapping:
			return mapping[date_text]

		# Try parsing as DD/MM/YYYY"
		return datetime.strptime(date_text, "%d/%m/%Y").date()
	except (ValueError, AttributeError):
		return None