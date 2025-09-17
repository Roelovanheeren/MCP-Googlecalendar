import os
import json
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz

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
    print(f"Request: {request.method} {request.url}")
    print(f"Headers: {dict(request.headers)}")
    response = await call_next(request)
    print(f"Response: {response.status_code}")
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
        # Get OAuth credentials from environment
        oauth_creds_json = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
        if not oauth_creds_json:
            raise HTTPException(status_code=500, detail="GOOGLE_OAUTH_CREDENTIALS not set")
        
        try:
            oauth_creds = json.loads(oauth_creds_json)
            credentials = Credentials.from_authorized_user_info(oauth_creds.get("installed", {}))
            
            # Build the service
            calendar_service = build('calendar', 'v3', credentials=credentials)
        except Exception as e:
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
async def mcp_handler(request):
    try:
        if isinstance(request, dict):
            return await handle_mcp_request(request)
        else:
            return {"error": "Invalid request format"}
    except Exception as e:
        print(f"Error in mcp_handler: {e}")
        return {"error": str(e)}

@app.post("/mcp")
async def mcp_handler_alt(request):
    try:
        if isinstance(request, dict):
            return await handle_mcp_request(request)
        else:
            return {"error": "Invalid request format"}
    except Exception as e:
        print(f"Error in mcp_handler_alt: {e}")
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

async def handle_mcp_request(request: dict):
    print(f"Received MCP request: {request}")
    
    # Handle different request formats
    if isinstance(request, dict):
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")
    else:
        print(f"Unexpected request type: {type(request)}")
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            }
        }
    
    if method == "tools/list":
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
