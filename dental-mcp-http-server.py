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
CLINIC_TIMEZONE = "Europe/Amsterdam"
BUSINESS_HOURS_START = "09:00"
BUSINESS_HOURS_END = "17:00"
WORKING_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]

def get_calendar_service():
    global calendar_service
    if calendar_service is None:
        try:
            # First try to use stored credentials from OAuth flow
            stored_credentials = os.environ.get("GOOGLE_CREDENTIALS")
            if stored_credentials:
                credentials_data = json.loads(stored_credentials)
                credentials = Credentials.from_authorized_user_info(credentials_data)
                logger.info("Using stored OAuth credentials")
            else:
                # Fallback to environment credentials
                oauth_creds_json = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
                if not oauth_creds_json:
                    raise Exception("No Google credentials available. Please authenticate first at /auth")
                
                oauth_creds = json.loads(oauth_creds_json)
                credentials = Credentials.from_authorized_user_info(oauth_creds.get("installed", {}))
                logger.info("Using environment credentials")
            
            # Build the service
            calendar_service = build('calendar', 'v3', credentials=credentials)
            logger.info("Calendar service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize calendar service: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to initialize calendar service: {str(e)}")
    
    return calendar_service

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
        # Initialize the OAuth flow
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
                    "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": []
                }
            },
            SCOPES
        )
        
        # Get the authorization URL with redirect_uri
        auth_url, _ = flow.authorization_url(
            prompt='consent',
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'
        )
        
        return {
            "message": "Please visit this URL to authenticate:",
            "auth_url": auth_url,
            "instructions": "After authentication, copy the authorization code and use it with /auth/callback?code=YOUR_CODE"
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
        # Initialize the OAuth flow
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
                    "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": []
                }
            },
            SCOPES
        )
        
        # Exchange the code for tokens
        flow.fetch_token(code=code, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
        credentials = flow.credentials
        
        # Store the credentials (in production, use a secure storage)
        token_data = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes
        }
        
        # Save to environment or file (simplified for demo)
        os.environ["GOOGLE_CREDENTIALS"] = json.dumps(token_data)
        
        return {
            "message": "Authentication successful!",
            "status": "authenticated"
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
                        "description": "Cancel an appointment",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "event_id": {"type": "string"},
                                "reason": {"type": "string"}
                            },
                            "required": ["event_id"]
                        }
                    },
                    {
                        "name": "reschedule_appointment",
                        "description": "Reschedule an appointment",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "event_id": {"type": "string"},
                                "new_date": {"type": "string"},
                                "new_time": {"type": "string"}
                            },
                            "required": ["event_id", "new_date", "new_time"]
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
                result = await cancel_appointment(arguments)
            elif tool_name == "reschedule_appointment":
                result = await reschedule_appointment(arguments)
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
    date_str = args.get("date")
    if not date_str:
        raise ValueError("Date is required")
    
    service = get_calendar_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    
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

async def book_appointment(args):
    patient_name = args.get("patient_name")
    patient_email = args.get("patient_email")
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
        'description': f'Type: {appointment_type}\nPatiënt: {patient_name}\nEmail: {patient_email}',
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("dental-mcp-http-server:app", host="0.0.0.0", port=port)
