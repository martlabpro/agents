import os
from typing import Optional, Annotated, List, Dict, Any
from typing_extensions import TypedDict
# from typing import TypedDict
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

from langgraph.graph import START, StateGraph
from langgraph.prebuilt import tools_condition


from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph.message import add_messages
from langgraph.graph import MessagesState, StateGraph, START
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.graph.state import CompiledStateGraph
from sqlmodel import SQLModel, Field, Session, create_engine, select, Column, String
import bcrypt
from email.message import EmailMessage
import smtplib
from langchain_google_genai import ChatGoogleGenerativeAI
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
import sqlite3

import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from sqlmodel import SQLModel, Field, Session, create_engine, select
from typing import Optional

# Load environment variables from the .env file
load_dotenv()

# Fetch the environment variables
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
MAIL_USERNAME = os.getenv('MAIL_USERNAME')
MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')



# Connection to Neon Database
DATABASE_URL = os.getenv('DATABASE_URL')
MEMORY_DATABASE=os.getenv('MEMORY_DATABASE')



llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", api_key=GOOGLE_API_KEY)


# Connection to Neon Database
# DATABASE_URL = userdata.get('DR_URL')



engine = create_engine(DATABASE_URL)




# Connection pool for efficient database access
connection_kwargs = {"autocommit": True, "prepare_threshold": 0}

# Create a persistent connection pool
pool = ConnectionPool(conninfo=MEMORY_DATABASE, max_size=20, kwargs=connection_kwargs)

# Initialize PostgresSaver checkpointer
checkpointer = PostgresSaver(pool)
checkpointer.setup()  # Ensure database tables are set up

# Define the User TypedDict
class User(TypedDict):
    role: str
    name: str
    email: str

# Define the State_Update TypedDict
class State_Update(MessagesState):
    user: Optional[User]


# SQLModel Schema for Doctor
class Doctor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)  # Doctor ID
    name: str  # Doctor's name
    specialty: str  # Doctor's specialty (e.g., 'Cardiologist')
    available: str  # Availability status



# SQLModel Schema for Appointment
class Appointment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)  # Appointment ID
    doctor_id: int  # Foreign key to Doctor
    patient_name: str  # Patient's name
    date: str  # Appointment date
    time: str  # Appointment time
    status: str = "Booked"  # Default status ("Booked", "Completed", "Cancelled", etc.)
    patient_email: str
    send_notification: bool = Field(default=False)

def create_db_and_tables() -> None:
    """
    Creates the necessary database tables for Product.
    """
    # Dropping and recreating all tables for a fresh start
    SQLModel.metadata.create_all(engine)
    print("Database tables synced successfully.")

# Create database tables
create_db_and_tables()

# CRUD Operations for Doctors

def add_doctor(name: str, specialty: str, available: bool) -> Doctor:
    """
    Adds a new doctor to the database.

    """

    with Session(engine) as session:
        doctor = Doctor(name=name, specialty=specialty, available=available)
        session.add(doctor)
        session.commit()
        session.refresh(doctor)
        return doctor

def get_doctor(doctor_id: int) -> Optional[dict]:
    """
    Retrieves a doctor's information (name and speciality) by their doctor_id.

    Args:
        doctor_id: The ID of the doctor to retrieve.

    Returns:
        A dictionary containing the doctor's name and speciality,
        or None if no doctor is found with the given ID.
    """
    with Session(engine) as session:
        doctor = session.exec(select(Doctor).where(Doctor.id == doctor_id)).first()
        if doctor:
            return {"name": doctor.name, "speciality": doctor.specialty}
        else:
            return None

def update_doctor(doctor_id: int, name: Optional[str] = None, specialty: Optional[str] = None, available: Optional[bool] = None) -> Optional[Doctor]:
    """
    Updates a doctor's details by their ID.
    """
    with Session(engine) as session:
        doctor = session.exec(select(Doctor).where(Doctor.id == doctor_id)).first()
        if doctor:
            if name:
                doctor.name = name
            if specialty:
                doctor.specialty = specialty
            if available is not None:
                doctor.available = available
            session.add(doctor)
            session.commit()
            session.refresh(doctor)
            return doctor
        return None

def delete_doctor(doctor_id: int) -> bool:
    """
    Deletes a doctor from the database by their ID.
    """
    with Session(engine) as session:
        doctor = session.exec(select(Doctor).where(Doctor.id == doctor_id)).first()
        if doctor:
            session.delete(doctor)
            session.commit()
            return True
        return False



def get_appointments_by_user(id: int) -> list[Appointment]:
    """Retrieves all appointments for a specific user or patient by their ID.

    Args:
        id: The ID of the user or patient.

    Returns:
        A list of Appointment objects, or an empty list if no appointments are found.
    """
    with Session(engine) as session:
        appointments = session.exec(select(Appointment).where(Appointment.id == id)).all()
        return appointments


def get_appointments_by_patient_name(patient_name: str) -> List[Appointment]:
    """Retrieves all appointments for a specific patient by their name.

    Args:
        patient_name: The name of the patient.

    Returns:
        A list of Appointment objects and get name of Doctor from get_doctor function, or an empty list if no appointments are found.
        Prints a message if no appointments are found for the given patient name.
    """
    with Session(engine) as session:
        # Query to get appointments based on patient_name
        appointments = session.exec(
            select(Appointment).where(Appointment.patient_name == patient_name)
        ).all()

        if not appointments:
             print(f"No appointments found for patient: {patient_name}")
        return appointments



def update_appointment(appointment_id: int, status: str) -> Optional[Appointment]:
    """
    Updates the status of an existing appointment (e.g., 'Completed').
    """
    with Session(engine) as session:
        appointment = session.exec(select(Appointment).where(Appointment.id == appointment_id)).first()
        if appointment:
            appointment.status = status
            session.add(appointment)
            session.commit()
            session.refresh(appointment)
        return appointment

def delete_appointment(appointment_id: int) -> bool:
    """
    Deletes an appointment from the database by appointment ID.
    """
    with Session(engine) as session:
        appointment = session.exec(select(Appointment).where(Appointment.id == appointment_id)).first()
        if appointment:
            session.delete(appointment)
            session.commit()
            return True
        return False


# Email Sending Function

def send_email(subject: str, body: str, to_email: str):
    """Sends an email using Gmail's SMTP server.

    This function uses the `smtplib` library to send an email
    with the given subject and body to the specified recipient email address.
    It uses Gmail's SMTP server for sending emails.

    Args:
        subject: The subject of the email.
        body: The body content of the email.
        to_email: The recipient's email address.

    Raises:
        Exception: If there is an error sending the email.
            The error message will be printed to the console.

    Prints:
        A success message if the email is sent successfully.
        An error message if there is an issue sending the email.
    """
    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = MAIL_USERNAME
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.send_message(msg)
        print(f"Email sent successfully to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")

def get_all_doctors() -> list[Doctor]:
    """Retrieves all doctors from the database.

    Returns:
        A list of Doctor objects representing all doctors in the database.
    """
    with Session(engine) as session:
        doctors = session.exec(select(Doctor)).all()
        return doctors


# CRUD Operations for Appointments

def get_appointment(appointment_id: int) -> Optional[Appointment]:
    """Retrieves a specific appointment by its ID.

    Args:
        appointment_id: The ID of the appointment to retrieve.

    Returns:
        The Appointment object if found, or None if no appointment with the given ID exists.
    """
    with Session(engine) as session:
        appointment = session.exec(select(Appointment).where(Appointment.id == appointment_id)).first()
        return appointment






def update_notification_status(appointment_id: int, send_notification: bool):
    """
    Updates the notification status for a given appointment.

    Args:
        appointment_id (int): The unique identifier of the appointment to update.
        send_notification (bool): The new value for the send_notification field.

    Raises:
        ValueError: If no appointment with the given ID is found.

    Returns:
        Dict[str, Any]: A dictionary containing the appointment ID and the updated notification status.
            Example: {
                "appointment_id": 123,
                "send_notification": True
            }
    """
    with Session(engine) as session:
        # Step 1: Fetch the appointment by ID
        appointment = session.get(Appointment, appointment_id)
        if not appointment:
            raise ValueError("Appointment not found.")

        # Step 2: Update the send_notification field
        appointment.send_notification = send_notification
        session.add(appointment)
        session.commit()

        # Step 3: Return the appointment ID and updated notification status
        return {
            "appointment_id": appointment.id,
            "send_notification": appointment.send_notification,
        }


# Tools with interup-------

#=======================================================
def book_appointment(data: Appointment,patient:str,email:str) -> Optional[Dict[str, Any]]:
    """
    Creates an appointment entry in the database and triggers a confirmation process.

    This function validates the user, creates an appointment entry in the database with
    `send_notification` defaulting to False, and raises a `NodeInterrupt` to pause the workflow
    for confirmation.

    Args:
        data (Appointment): The appointment details including doctor ID, patient name, date, time, etc.

    Raises:
        NodeInterrupt: Pauses the workflow for user confirmation to decide whether to send a notification.
        ValueError: If the patient is not found in the database.

    Returns:
        Optional[Dict[str, Any]]: None as this function relies on `NodeInterrupt` to pause and delegate further actions.
    """
    with Session(engine) as session:  # Assuming a globally available session factory


        data.patient_email = email  # Ensure the patient's email is set

        # Step 2: Insert appointment into the database
        appointment = Appointment(
            doctor_id=data.doctor_id,
            patient_name=patient,
            date=data.date,
            time=data.time,
            status=data.status or "Booked",
            patient_email=email,
            send_notification=False  # Default to False initially
        )
        session.add(appointment)
        session.commit()
        session.refresh(appointment)


        # Step 4: Trigger the NodeInterrupt for confirmation
        print("Raising NodeInterrupt; waiting for confirmation.")
        raise NodeInterrupt("Do you want me to send email notification. yes/no")

    return None




def handle_appointment_confirmation(appointment_id: int, notification_status: bool) -> Optional[Dict[str, Any]]:
    """
    Sends an email notification for an appointment if the user confirms the notification status or send to True.

    This function handles the confirmation of an appointment and sends an email
    notification if the user agrees to receive one. It updates the `send_notification`
    field in the appointment and sends an email if the status is set to True.

    Args:
        appointment_id (int): The ID of the appointment to confirm.
        notification_status (bool): True to send an email notification, False to skip.

    Raises:
        ValueError: If the specified appointment ID does not exist in the database.

    Returns:
        Optional[Dict[str, Any]]: A dictionary containing the appointment details if an email
        is sent, otherwise None.
    """
    with Session(engine) as session:  # Assuming a globally available session factory
        # Step 1: Fetch the appointment from the database
        appointment = session.get(Appointment, appointment_id)
        if not appointment:
            raise ValueError("Appointment not found.")

        # Step 2: Update the `send_notification` field based on input
        appointment.send_notification = notification_status
        session.add(appointment)
        session.commit()

        # Step 3: Handle email notification if confirmed
        if notification_status:
            doctor_name = get_doctor(appointment.doctor_id)['name']
            send_email(
                "Appointment Confirmation",
                f"Your appointment with Dr. {doctor_name} on {appointment.date} at {appointment.time} is confirmed.",
                appointment.patient_email,
            )
            print(f"Email notification sent to {appointment.patient_email}")
            return {
                "appointment_id": appointment.id,
                "status": appointment.status,
                "send_notification": appointment.send_notification,  # Corrected field name
            }
        else:
            print("Email notification skipped as per the user's request.")
            return None

# Tool calling
# # Define the tools for CRUD operations
tools=[
       add_doctor,
       get_doctor,
       update_doctor,
       delete_doctor,
    #    book_appointment,
       update_notification_status
       ,

       handle_appointment_confirmation,
       get_appointments_by_user,
       get_appointments_by_patient_name,
       update_appointment,
       delete_appointment,
      #  send_email,
       get_all_doctors,
       get_appointment,

       ]


llm_with_tools = llm.bind_tools(tools)

sys_prompt = """
You are a healthcare database manager. Your primary responsibilities include maintaining accurate records for doctors and appointments while ensuring users receive timely email notifications. Always confirm notifications before sending and maintain clear communication
"""

from langgraph.graph import MessagesState
from langchain_core.messages import HumanMessage, SystemMessage

# System message
sys_msg = SystemMessage(content=sys_prompt)


# Node
def assistant(state: MessagesState) -> MessagesState:
   return {"messages": [llm_with_tools.invoke([sys_msg] + state["messages"])]}

# pull file if it doesn't exist and connect to local db
# !mkdir -p state_db && [ ! -f state_db/example.db ]
db_path = "example.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
# Here is our checkpointer
memory: SqliteSaver = SqliteSaver(conn)




# Graph
builder: StateGraph = StateGraph(MessagesState)

# Define nodes: these do the work
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))

# Define edges: these determine how the control flow moves
builder.add_edge(START, "assistant")
builder.add_conditional_edges(
    "assistant",
    # If the latest message (result) from assistant is a tool call -> tools_condition routes to tools
    # If the latest message (result) from assistant is a not a tool call -> tools_condition routes to END
    tools_condition,
)
builder.add_edge("tools", "assistant")
# react_graph: CompiledStateGraph = builder.compile()
react_graph_memory: CompiledStateGraph = builder.compile(checkpointer=memory)

# Show
# display(Image(react_graph_memory.get_graph(xray=True).draw_mermaid_png()))

