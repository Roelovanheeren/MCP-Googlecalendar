import os
import json
import uvicorn
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz

# Google Calendar API scopes
SCOPES = ['https://www.googleapis.com/auth/calendar']

app = FastAPI(title="Dental Calendar MCP Server", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add logging middleware
@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"Request: {request.method} {request.url}")
    logger.info(f"Headers: {dict(request.headers)}")
    response = await call_next(request)
    logger.info(f"Response: {response.status_code}")
    return response

# Global variables
calendar_service = None
CLINIC_TIMEZONE = "Europe/Amsterdam"  # Netherlands timezone for dental practice
BUSINESS_HOURS_START = "09:00"
BUSINESS_HOURS_END = "17:00"
WORKING_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]

def get_calendar_service():
    global calendar_service
    if calendar_service is None:
        try:
            # First try to load from persistent file
            credentials_file = "google_credentials.json"
            if os.path.exists(credentials_file):
                with open(credentials_file, 'r') as f:
                    credentials_data = json.load(f)
                credentials = Credentials.from_authorized_user_info(credentials_data)
                logger.info("Using persistent OAuth credentials from file")
            else:
                # Try environment variable
                stored_credentials = os.environ.get("GOOGLE_CREDENTIALS")
                if stored_credentials:
                    credentials_data = json.loads(stored_credentials)
                    credentials = Credentials.from_authorized_user_info(credentials_data)
                    logger.info("Using stored OAuth credentials from environment")
                else:
                    # Fallback to environment credentials
                    oauth_creds_json = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
                    if not oauth_creds_json:
                        raise Exception("No Google credentials available. Please authenticate first at /auth")
                    
                    oauth_creds = json.loads(oauth_creds_json)
                    credentials = Credentials.from_authorized_user_info(oauth_creds.get("installed", {}))
                    logger.info("Using environment credentials")
            
            # Refresh credentials if needed
            if credentials and credentials.expired and credentials.refresh_token:
                logger.info("Refreshing expired credentials")
                credentials.refresh(GoogleRequest())
                # Save refreshed credentials
                credentials_data = {
                    "token": credentials.token,
                    "refresh_token": credentials.refresh_token,
                    "token_uri": credentials.token_uri,
                    "client_id": credentials.client_id,
                    "client_secret": credentials.client_secret,
                    "scopes": credentials.scopes
                }
                with open(credentials_file, 'w') as f:
                    json.dump(credentials_data, f)
                logger.info("Refreshed credentials saved")
            
            # Build the service
            calendar_service = build('calendar', 'v3', credentials=credentials)
            logger.info("Calendar service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {e}")
            # Don't raise exception here, let individual functions handle it
            return None
    
    return calendar_service

async def find_appointment_by_patient_info(patient_name, appointment_date, patient_phone=None, appointment_time=None):
    """Find appointment by patient information instead of event ID"""
    try:
        service = get_calendar_service()
        
        # Convert date to datetime range
        start_date = datetime.strptime(appointment_date, '%Y-%m-%d')
        end_date = start_date + timedelta(days=1)
        
        # Convert to UTC
        amsterdam_tz = pytz.timezone('Europe/Amsterdam')
        start_datetime = amsterdam_tz.localize(start_date).astimezone(pytz.UTC)
        end_datetime = amsterdam_tz.localize(end_date).astimezone(pytz.UTC)
        
        # Search for events
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_datetime.isoformat(),
            timeMax=end_datetime.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        matches = []
        
        for event in events:
            summary = event.get('summary', '').lower()
            attendees = event.get('attendees', [])
            
            # Check if patient name matches
            if patient_name.lower() in summary:
                # If time is specified, check if it matches
                if appointment_time:
                    event_start = event.get('start', {}).get('dateTime', '')
                    if event_start:
                        event_time = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                        amsterdam_time = event_time.astimezone(amsterdam_tz)
                        event_time_str = amsterdam_time.strftime('%H:%M')
                        if event_time_str == appointment_time:
                            matches.append(event)
                else:
                    matches.append(event)
            
            # Also check attendees
            for attendee in attendees:
                attendee_email = attendee.get('email', '').lower()
                attendee_name = attendee.get('displayName', '').lower()
                if (patient_name.lower() in attendee_email or 
                    patient_name.lower() in attendee_name):
                    if appointment_time:
                        event_start = event.get('start', {}).get('dateTime', '')
                        if event_start:
                            event_time = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                            amsterdam_time = event_time.astimezone(amsterdam_tz)
                            event_time_str = amsterdam_time.strftime('%H:%M')
                            if event_time_str == appointment_time:
                                matches.append(event)
                    else:
                        matches.append(event)
        
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            # Return the first match with a flag indicating multiple matches
            result = matches[0]
            result['_multiple_matches'] = len(matches)
            return result
        else:
            return None
            
    except Exception as e:
        logger.error(f"Error finding appointment: {e}")
        return None

def parse_date_flexible(date_str):
    """Parse date in various formats"""
    try:
        # Try different date formats
        formats = ['%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d']
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        # If none work, try to parse with dateutil
        from dateutil import parser
        return parser.parse(date_str)
    except Exception as e:
        logger.error(f"Error parsing date {date_str}: {e}")
        return datetime.now()

@app.get("/")
async def root():
    return {
        "status": "ok",
        "server": "dental-calendar-mcp",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    return "ok"

@app.get("/status")
async def status():
    """Detailed status endpoint for debugging"""
    service = get_calendar_service()
    has_oauth_creds = bool(os.environ.get("GOOGLE_OAUTH_CREDENTIALS"))
    has_stored_creds = bool(os.environ.get("GOOGLE_CREDENTIALS"))
    has_credentials_file = os.path.exists("google_credentials.json")
    
    return {
        "status": "running",
        "calendar_service_available": service is not None,
        "has_oauth_credentials": has_oauth_creds,
        "has_stored_credentials": has_stored_creds,
        "has_credentials_file": has_credentials_file,
        "calendar_id": os.environ.get("GOOGLE_CALENDAR_ID", "not_set"),
        "timestamp": datetime.now().isoformat()
    }

@app.post("/")
async def mcp_handler(request: Request):
    try:
        body = await request.json()
        logger.info(f"Received MCP request at /: {body}")
        return await handle_mcp_request(body)
    except Exception as e:
        logger.error(f"Error in mcp_handler: {e}")
        return {"error": str(e)}

@app.post("/mcp")
async def mcp_handler_alt(request: Request):
    try:
        body = await request.json()
        logger.info(f"ElevenLabs POST request to /mcp: {body}")
        logger.info(f"Request headers: {dict(request.headers)}")
        return await handle_mcp_request(body)
    except Exception as e:
        logger.error(f"Error in mcp_handler_alt: {e}")
        return {"error": str(e)}

@app.get("/mcp/info")
async def mcp_info():
    return {
        "protocol": "mcp",
        "version": "1.0.0",
        "capabilities": {
            "tools": True
        },
        "server": "dental-calendar-mcp"
    }

@app.get("/mcp")
async def mcp_info():
    """GET endpoint that ElevenLabs calls first to validate the server"""
    logger.info("ElevenLabs GET request to /mcp")
    return {
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "dental-calendar-mcp",
                "version": "1.0.0"
            }
        }
    }

@app.get("/mcp/status")
async def mcp_status():
    """Additional status endpoint"""
    return {
        "status": "ok",
        "message": "MCP server is running",
        "tools_available": 6
    }

@app.get("/auth")
async def auth_redirect():
    """Redirect to Google OAuth for authentication"""
    try:
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        if not client_id:
            return {"error": "GOOGLE_CLIENT_ID not set"}
        
        # Create the authorization URL manually
        auth_url = (
            f"https://accounts.google.com/o/oauth2/auth?"
            f"response_type=code&"
            f"client_id={client_id}&"
            f"scope=https://www.googleapis.com/auth/calendar&"
            f"redirect_uri=http://localhost&"
            f"prompt=consent&"
            f"access_type=offline"
        )
        
        return {
            "message": "Please visit this URL to authenticate:",
            "auth_url": auth_url,
            "instructions": "After authentication, copy the authorization code and use it with /auth/callback?code=YOUR_CODE",
            "note": "This is a ONE-TIME setup. After authentication, the service will work permanently."
        }
    except Exception as e:
        logger.error(f"Auth error: {e}")
        return {"error": str(e)}

@app.get("/auth/callback")
async def auth_callback(code: str = None):
    """Handle OAuth callback and store tokens"""
    if not code:
        return {"error": "No authorization code provided"}
    
    try:
        import requests
        
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            return {"error": "Google credentials not configured"}
        
        # Exchange the code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": "http://localhost",
            "grant_type": "authorization_code"
        }
        
        response = requests.post(token_url, data=token_data)
        token_response = response.json()
        
        if "error" in token_response:
            return {"error": f"Token exchange failed: {token_response['error']}"}
        
        # Store the credentials
        credentials_data = {
            "token": token_response["access_token"],
            "refresh_token": token_response.get("refresh_token"),
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": ["https://www.googleapis.com/auth/calendar"]
        }
        
        # Save to persistent file in the app directory
        credentials_file = "google_credentials.json"
        with open(credentials_file, 'w') as f:
            json.dump(credentials_data, f)
        
        # Also save to environment for immediate use
        os.environ["GOOGLE_CREDENTIALS"] = json.dumps(credentials_data)
        
        # Reset the global service to force reinitialization
        global calendar_service
        calendar_service = None
        
        return {
            "message": "Authentication successful! The service is now permanently configured.",
            "status": "authenticated",
            "expires_in": token_response.get("expires_in"),
            "note": "You will not need to authenticate again. The service will automatically refresh tokens when needed."
        }
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return {"error": str(e)}

async def handle_mcp_request(request: dict):
    logger.info(f"Received MCP request: {request}")
    
    # Handle different request formats
    if isinstance(request, dict):
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
    else:
        logger.error(f"Unexpected request type: {type(request)}")
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            }
        }
    
    if method == "initialize":
        logger.info("ElevenLabs initialize request")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "dental-calendar-mcp",
                    "version": "1.0.0"
                }
            }
        }
    elif method == "tools/list":
        logger.info("Returning tools list")
        # Try a simpler format that ElevenLabs might expect
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": "check_available_slots",
                        "description": "Check available appointment slots for a specific date",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"}
                            },
                            "required": ["date"]
                        }
                    },
                    {
                        "name": "book_appointment",
                        "description": "Book a new appointment",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "patient_name": {"type": "string"},
                                "patient_email": {"type": "string"},
                                "patient_phone": {"type": "string"},
                                "date": {"type": "string"},
                                "time": {"type": "string"},
                                "appointment_type": {"type": "string"}
                            },
                            "required": ["patient_name", "patient_email", "date", "time", "appointment_type"]
                        }
                    },
                    {
                        "name": "list_appointments",
                        "description": "List appointments in a date range",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "start_date": {"type": "string"},
                                "end_date": {"type": "string"}
                            },
                            "required": ["start_date", "end_date"]
                        }
                    },
                    {
                        "name": "get_appointment_details",
                        "description": "Get details of a specific appointment",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "event_id": {"type": "string"}
                            },
                            "required": ["event_id"]
                        }
                    },
                    {
                        "name": "cancel_appointment",
                        "description": "Cancel an appointment using patient information",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "patient_name": {"type": "string", "description": "Name of the patient"},
                                "appointment_date": {"type": "string", "description": "Date of the appointment (YYYY-MM-DD)"},
                                "appointment_time": {"type": "string", "description": "Time of the appointment (HH:MM)"},
                                "reason": {"type": "string", "description": "Reason for cancellation"}
                            },
                            "required": ["patient_name", "appointment_date"]
                        }
                    },
                    {
                        "name": "reschedule_appointment",
                        "description": "Reschedule an appointment using patient information",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "patient_name": {"type": "string", "description": "Name of the patient"},
                                "current_date": {"type": "string", "description": "Current appointment date (YYYY-MM-DD)"},
                                "current_time": {"type": "string", "description": "Current appointment time (HH:MM)"},
                                "new_date": {"type": "string", "description": "New appointment date (YYYY-MM-DD)"},
                                "new_time": {"type": "string", "description": "New appointment time (HH:MM)"}
                            },
                            "required": ["patient_name", "current_date", "new_date", "new_time"]
                        }
                    }
                ]
            }
        }
    
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        try:
            if tool_name == "check_available_slots":
                result = await check_available_slots(arguments)
            elif tool_name == "book_appointment":
                result = await book_appointment(arguments)
            elif tool_name == "list_appointments":
                result = await list_appointments(arguments)
            elif tool_name == "get_appointment_details":
                result = await get_appointment_details(arguments)
            elif tool_name == "cancel_appointment":
                result = await cancel_appointment_by_patient(arguments)
            elif tool_name == "reschedule_appointment":
                result = await reschedule_appointment_by_patient(arguments)
            else:
                raise HTTPException(status_code=400, detail=f"Unknown tool: {tool_name}")
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result)}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown method: {method}")

async def check_available_slots(args):
    try:
        date_str = args.get("date")
        if not date_str:
            raise ValueError("Date is required")
        
        logger.info(f"Checking available slots for date: {date_str}")
        service = get_calendar_service()
        if service is None:
            raise Exception("Google Calendar service not available. Please authenticate first at /auth")
        calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        logger.info(f"Using calendar ID: {calendar_id}")
        
        # Parse date and create time range
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        amsterdam_tz = pytz.timezone(CLINIC_TIMEZONE)
        
        # Business hours
        start_time = amsterdam_tz.localize(datetime.combine(date_obj, datetime.strptime(BUSINESS_HOURS_START, "%H:%M").time()))
        end_time = amsterdam_tz.localize(datetime.combine(date_obj, datetime.strptime(BUSINESS_HOURS_END, "%H:%M").time()))
        
        # Get existing events
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=start_time.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        # Generate available slots (30-minute intervals)
        available_slots = []
        current_time = start_time
        
        while current_time < end_time:
            slot_end = current_time + timedelta(minutes=30)
            
            # Check if slot conflicts with existing events
            conflict = False
            for event in events:
                event_start = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
                event_end = datetime.fromisoformat(event['end']['dateTime'].replace('Z', '+00:00'))
                
                if (current_time < event_end and slot_end > event_start):
                    conflict = True
                    break
            
            if not conflict:
                available_slots.append({
                    "time": current_time.strftime("%H:%M"),
                    "datetime": current_time.isoformat()
                })
            
            current_time += timedelta(minutes=30)
        
        return {
            "date": date_str,
            "available_slots": available_slots,
            "business_hours": f"{BUSINESS_HOURS_START} - {BUSINESS_HOURS_END}"
        }
    except Exception as e:
        logger.error(f"Error in check_available_slots: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check available slots: {str(e)}")

async def book_appointment(args):
    patient_name = args.get("patient_name")
    patient_email = args.get("patient_email")
    patient_phone = args.get("patient_phone")
    date_str = args.get("date")
    time_str = args.get("time")
    appointment_type = args.get("appointment_type")
    
    if not all([patient_name, patient_email, date_str, time_str, appointment_type]):
        raise ValueError("All fields are required")
    
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    
    # Create event
    amsterdam_tz = pytz.timezone(CLINIC_TIMEZONE)
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    time_obj = datetime.strptime(time_str, "%H:%M").time()
    
    start_datetime = amsterdam_tz.localize(datetime.combine(date_obj, time_obj))
    end_datetime = start_datetime + timedelta(minutes=30)
    
    event = {
        'summary': f'Afspraak - {patient_name}',
        'description': f'Type: {appointment_type}\nPatiënt: {patient_name}\nEmail: {patient_email}\nTelefoon: {patient_phone or "Niet opgegeven"}',
        'start': {
            'dateTime': start_datetime.isoformat(),
            'timeZone': CLINIC_TIMEZONE,
        },
        'end': {
            'dateTime': end_datetime.isoformat(),
            'timeZone': CLINIC_TIMEZONE,
        },
        'attendees': [
            {'email': patient_email, 'displayName': patient_name}
        ],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                {'method': 'popup', 'minutes': 30},       # 30 minutes before
            ],
        },
    }
    
    created_event = service.events().insert(calendarId=calendar_id, body=event).execute()
    
    return {
        "success": True,
        "event_id": created_event['id'],
        "message": f"Afspraak geboekt voor {patient_name} op {date_str} om {time_str}",
        "event": created_event
    }

async def list_appointments(args):
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    
    if not start_date or not end_date:
        raise ValueError("Start date and end date are required")
    
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    
    amsterdam_tz = pytz.timezone(CLINIC_TIMEZONE)
    start_datetime = amsterdam_tz.localize(datetime.strptime(start_date, "%Y-%m-%d"))
    end_datetime = amsterdam_tz.localize(datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1))
    
    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_datetime.isoformat(),
        timeMax=end_datetime.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    
    events = events_result.get('items', [])
    
    appointments = []
    for event in events:
        if 'dateTime' in event.get('start', {}):
            appointments.append({
                "id": event['id'],
                "summary": event.get('summary', ''),
                "start": event['start']['dateTime'],
                "end": event['end']['dateTime'],
                "description": event.get('description', ''),
                "attendees": event.get('attendees', [])
            })
    
    return {
        "appointments": appointments,
        "count": len(appointments)
    }

async def get_appointment_details(args):
    event_id = args.get("event_id")
    if not event_id:
        raise ValueError("Event ID is required")
    
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    
    return {
        "id": event['id'],
        "summary": event.get('summary', ''),
        "start": event.get('start', {}),
        "end": event.get('end', {}),
        "description": event.get('description', ''),
        "attendees": event.get('attendees', []),
        "status": event.get('status', '')
    }

async def cancel_appointment(args):
    event_id = args.get("event_id")
    reason = args.get("reason", "Geannuleerd door patiënt")
    
    if not event_id:
        raise ValueError("Event ID is required")
    
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    
    # Update event with cancellation note
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    event['summary'] = f"[GEANNULEERD] {event.get('summary', '')}"
    event['description'] = f"{event.get('description', '')}\n\nReden annulering: {reason}"
    
    updated_event = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
    
    return {
        "success": True,
        "message": f"Afspraak {event_id} is geannuleerd",
        "reason": reason
    }

async def reschedule_appointment(args):
    event_id = args.get("event_id")
    new_date = args.get("new_date")
    new_time = args.get("new_time")
    
    if not all([event_id, new_date, new_time]):
        raise ValueError("Event ID, new date, and new time are required")
    
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    
    # Get existing event
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    
    # Update times
    amsterdam_tz = pytz.timezone(CLINIC_TIMEZONE)
    date_obj = datetime.strptime(new_date, "%Y-%m-%d")
    time_obj = datetime.strptime(new_time, "%H:%M").time()
    
    new_start = amsterdam_tz.localize(datetime.combine(date_obj, time_obj))
    new_end = new_start + timedelta(minutes=30)
    
    event['start'] = {
        'dateTime': new_start.isoformat(),
        'timeZone': CLINIC_TIMEZONE,
    }
    event['end'] = {
        'dateTime': new_end.isoformat(),
        'timeZone': CLINIC_TIMEZONE,
    }
    
    updated_event = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
    
    return {
        "success": True,
        "message": f"Afspraak {event_id} is verzet naar {new_date} om {new_time}",
        "new_start": new_start.isoformat(),
        "new_end": new_end.isoformat()
    }

async def cancel_appointment_by_patient(args):
    """Cancel appointment using patient information instead of event ID"""
    try:
        patient_name = args.get('patient_name')
        appointment_date = args.get('appointment_date')
        appointment_time = args.get('appointment_time')
        reason = args.get('reason', 'Geannuleerd door patiënt')
        
        if not patient_name or not appointment_date:
            return {
                "success": False,
                "error": "Patient name and appointment date are required",
                "message": "Ik heb de patiëntnaam en afspraakdatum nodig om de afspraak te annuleren."
            }
        
        # Find the appointment
        event = await find_appointment_by_patient_info(
            patient_name=patient_name,
            appointment_date=appointment_date,
            appointment_time=appointment_time
        )
        
        if not event:
            return {
                "success": False,
                "error": "Appointment not found",
                "message": f"Ik kon geen afspraak vinden voor {patient_name} op {appointment_date}. Kunt u de datum en tijd nog eens controleren?"
            }
        
        # Handle multiple matches
        if event.get('_multiple_matches', 0) > 1:
            event_time = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
            amsterdam_tz = pytz.timezone('Europe/Amsterdam')
            local_time = event_time.astimezone(amsterdam_tz)
            
            return {
                "success": False,
                "multiple_matches": True,
                "message": f"Ik vond meerdere afspraken voor {patient_name}. Bedoelt u de afspraak op {local_time.strftime('%d %B om %H:%M')} te annuleren?",
                "found_appointment": {
                    "date": local_time.strftime('%Y-%m-%d'),
                    "time": local_time.strftime('%H:%M'),
                    "summary": event.get('summary', '')
                }
            }
        
        # Cancel the appointment
        service = get_calendar_service()
        calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        
        # Update event with cancellation note
        event['summary'] = f"[GEANNULEERD] {event.get('summary', '')}"
        event['description'] = f"{event.get('description', '')}\n\nReden annulering: {reason}"
        
        updated_event = service.events().update(
            calendarId=calendar_id, 
            eventId=event['id'], 
            body=event
        ).execute()
        
        return {
            "success": True,
            "message": f"Afspraak voor {patient_name} op {appointment_date} is succesvol geannuleerd",
            "reason": reason,
            "cancelled_appointment": {
                "patient": patient_name,
                "date": appointment_date,
                "time": appointment_time
            }
        }
        
    except Exception as e:
        logger.error(f"Error cancelling appointment: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Er ging iets mis bij het annuleren van de afspraak"
        }

async def reschedule_appointment_by_patient(args):
    """Reschedule appointment using patient information instead of event ID"""
    try:
        patient_name = args.get('patient_name')
        current_date = args.get('current_date')
        current_time = args.get('current_time')
        new_date = args.get('new_date')
        new_time = args.get('new_time')
        
        if not all([patient_name, current_date, new_date, new_time]):
            return {
                "success": False,
                "error": "Missing required parameters",
                "message": "Ik heb de patiëntnaam, huidige datum, nieuwe datum en nieuwe tijd nodig om de afspraak te verzetten."
            }
        
        # Find the current appointment
        event = await find_appointment_by_patient_info(
            patient_name=patient_name,
            appointment_date=current_date,
            appointment_time=current_time
        )
        
        if not event:
            return {
                "success": False,
                "error": "Appointment not found",
                "message": f"Ik kon geen afspraak vinden voor {patient_name} op {current_date}. Kunt u de huidige datum en tijd nog eens controleren?"
            }
        
        # Handle multiple matches
        if event.get('_multiple_matches', 0) > 1:
            event_time = datetime.fromisoformat(event['start']['dateTime'].replace('Z', '+00:00'))
            amsterdam_tz = pytz.timezone('Europe/Amsterdam')
            local_time = event_time.astimezone(amsterdam_tz)
            
            return {
                "success": False,
                "multiple_matches": True,
                "message": f"Ik vond meerdere afspraken voor {patient_name}. Bedoelt u de afspraak op {local_time.strftime('%d %B om %H:%M')} te verzetten?",
                "found_appointment": {
                    "date": local_time.strftime('%Y-%m-%d'),
                    "time": local_time.strftime('%H:%M'),
                    "summary": event.get('summary', '')
                }
            }
        
        # Check availability for new time
        available_slots = await check_available_slots({"date": new_date})
        available_data = json.loads(available_slots.get("available_slots", "[]"))
        
        # Check if new time is available
        new_time_available = any(slot["time"] == new_time for slot in available_data)
        if not new_time_available:
            available_times = [slot["time"] for slot in available_data[:5]]
            return {
                "success": False,
                "error": "Time slot not available",
                "message": f"De tijd {new_time} op {new_date} is niet beschikbaar. Beschikbare tijden: {', '.join(available_times)}",
                "available_slots": available_data,
                "suggested_times": available_times
            }
        
        # Update the appointment
        service = get_calendar_service()
        calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
        
        # Parse new date and time
        new_datetime = parse_date_flexible(new_date)
        if ':' in new_time:
            hour, minute = map(int, new_time.split(':'))
            new_datetime = new_datetime.replace(hour=hour, minute=minute)
        
        # Convert to UTC for Google Calendar
        amsterdam_tz = pytz.timezone('Europe/Amsterdam')
        new_datetime_utc = amsterdam_tz.localize(new_datetime).astimezone(pytz.UTC)
        end_datetime_utc = new_datetime_utc + timedelta(minutes=30)  # 30 min appointment
        
        # Update the event
        updated_event = {
            'start': {'dateTime': new_datetime_utc.isoformat()},
            'end': {'dateTime': end_datetime_utc.isoformat()},
        }
        
        result = service.events().patch(
            calendarId=calendar_id,
            eventId=event['id'],
            body=updated_event
        ).execute()
        
        return {
            "success": True,
            "message": f"Afspraak voor {patient_name} succesvol verzet naar {new_date} om {new_time}",
            "rescheduled_appointment": {
                "patient": patient_name,
                "old_date": current_date,
                "old_time": current_time,
                "new_date": new_date,
                "new_time": new_time
            }
        }
        
    except Exception as e:
        logger.error(f"Error rescheduling appointment: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Er ging iets mis bij het verzetten van de afspraak"
        }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("dental-mcp-http-server:app", host="0.0.0.0", port=port)
