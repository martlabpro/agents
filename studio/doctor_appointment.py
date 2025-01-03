from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.types import Command, interrupt
from langgraph.graph import START, StateGraph, MessagesState
from langgraph.prebuilt import tools_condition, ToolNode
from langgraph.graph.state import CompiledStateGraph
from typing import Dict,Any
# tools definitions
#==============================
from sqlmodel import Session, select
from typing import Optional,List
import bcrypt
from email.message import EmailMessage
import smtplib


from sqlmodel import SQLModel, Field, create_engine, Session, select, Column, String
from typing import Optional
import os
# Define the path for the SQLite database in Google Drive
db_path = "/local_database.db"

# Ensure the directory exists
if not os.path.exists(os.path.dirname(db_path)):
    os.makedirs(os.path.dirname(db_path))


MAIL_USERNAME = os.environ['MAIL_USERNAME']
MAIL_PASSWORD = os.environ['MAIL_PASSWORD']

DATABASE_URL = os.environ['DATABASE_URL']
MEMORY_DATABASE = os.environ['DB_URL']



engine = create_engine(DATABASE_URL)


# Function to set up the database
# def setup_database(db_url=f"sqlite:///{db_path}"):
#     print(f"Using database at: {db_url}")
#     engine = create_engine(db_url)
#     SQLModel.metadata.create_all(engine)
#     return engine

# # Set up the database connection (SQLite stored in Google Drive)
# engine = setup_database()

from sqlmodel import SQLModel, Field, Column, String
from typing import Optional
from langgraph.checkpoint.memory import MemorySaver
# SQLModel Schema for User
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(sa_column=Column(String, unique=True, index=True))  # Username field
    password: str  # Hashed password
    role: str  # Role ('admin' or 'user')
    email: str = Field(sa_column=Column(String, unique=True, index=True))  # Email field for unique identification

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
    patient_email: str  # Patient's email for notifications
    date: str  # Appointment date
    time: str  # Appointment time
    status: str = "Booked"  # Default status ("Booked", "Completed", "Cancelled", etc.)
    send_notification: bool = Field(default=False)  # Notification status



def create_db_and_tables() -> None:
    """
    Creates the necessary database tables for Product.
    """
    # Dropping and recreating all tables for a fresh start
    SQLModel.metadata.create_all(engine)
    print("Database tables synced successfully.")

# Create database tables
create_db_and_tables()

#==============================
from sqlmodel import Session, select
from typing import Optional,List
import bcrypt
from email.message import EmailMessage
import smtplib

# CRUD Operations for Users

def signup(username: str, password: str, role: str = 'user', email: str = '') -> User:
    """
    Registers a new user.
    """
    role = role.lower()
    if role not in ['admin', 'user']:
        raise ValueError("Invalid role! Role must be either 'admin' or 'user'.")

    if not email or '@' not in email:
        raise ValueError("Invalid email address.")

    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    with Session(engine) as session:
        if session.exec(select(User).where(User.username == username.lower())).first():
            raise ValueError("Username already exists!")
        if session.exec(select(User).where(User.email == email)).first():
            raise ValueError("Email already exists!")

        user = User(username=username, password=hashed_password, role=role, email=email)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

def signin(username: str, password: str):
    """
    Authenticates a user and returns the User object if successful.

    Args:
        username: The username of the user.
        password: The plain-text password entered by the user.
        session: An active SQLModel Session.

    Returns:
        The User object if the login is successful, otherwise None.
    """
    with Session(engine) as session:
      statement = select(User).where(User.username == username.lower())
      result = session.exec(statement)
      user = result.first()

      if user and bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')): 
          return user
      else:
          return {"error":"username or password is invalid"} 
        

def delete_user(user_id: int) -> bool:
    """
    Deletes a user by their ID (Admin Only).
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.id == user_id)).first()
        if user:
            session.delete(user)
            session.commit()
            return True
        return False


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

def get_doctor(doctor_id: int) -> Optional[Doctor]:
    """
    Retrieves a doctor's details from the database by their doctor_id.
    """
    with Session(engine) as session:
        doctor = session.exec(select(Doctor).where(Doctor.id == doctor_id)).first()
        return doctor

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


# CRUD Operations for Appointments


def book_appointment(data: Appointment) -> Optional[Dict[str, Any]]:
    """
    Booked appointment and asked patient during interrup what email nodification if yes than tool send_notification is called.
    """
    with Session(engine) as session:
        # Fetch user details from the User table based on the patient's username
        user = session.query(User).filter(User.username == data.patient_name).first()
        if not user:
            raise ValueError(f"User with username '{data.patient_name}' not found.")

        # Insert appointment into the database
        appointment = Appointment(
            doctor_id=data.doctor_id,
            patient_name=user.username,  # Use username as patient_name
            patient_email=user.email,   # Fetch email from User table
            date=data.date,
            time=data.time,
            status=data.status or "Booked",
            send_notification=False  # Default to False initially
        )
        session.add(appointment)
        session.commit()
        session.refresh(appointment)

        # Trigger the NodeInterrupt for confirmation
        print("Raising NodeInterrupt; waiting for confirmation.")
        notification_status = interrupt("Do you want me to send email notification? yes/no")

        if notification_status == "yes":
            appointment.send_notification = True
            session.add(appointment)
            session.commit()

        return {"appointment_id": appointment.id, "notification_status": appointment.send_notification}

def send_notification(appointment_id: int, notification_status: bool) -> Optional[Dict[str, Any]]:
    """
    Sends an email notification for an appointment if the user confirms the notification status as true or yes.
    Args:
        appointment_id (int): The ID of the appointment to confirm.
        notification_status (bool): True or False.
    """
    with Session(engine) as session:
        # Step 1: Fetch the appointment from the database
        appointment = session.get(Appointment, appointment_id)
        if not appointment:
            raise ValueError("Appointment not found.")

        # Step 2: Fetch doctor details
        doctor = session.get(Doctor, appointment.doctor_id)
        if not doctor:
            raise ValueError("Doctor not found.")

        # Step 3: Update the `send_notification` field based on input
        appointment.send_notification = notification_status
        session.add(appointment)
        session.commit()

        # Step 4: Handle email notification if confirmed
        if notification_status:
            send_email(
                "Appointment Confirmation",
                f"Your appointment with Dr. {doctor.name} on {appointment.date} at {appointment.time} is confirmed.",
                appointment.patient_email,  # Use the updated field
            )
            print(f"Email notification sent to {appointment.patient_email}")
            return {
                "appointment_id": appointment.id,
                "status": appointment.status,
                "send_notification": appointment.send_notification,
            }
        else:
            print("Email notification skipped as per the user's request.")
            return None


def get_appointments_by_user(id: int) -> list[Appointment]:
    """
    Retrieves all appointments for a specific user or patient.
    """
    with Session(engine) as session:
        appointments = session.exec(select(Appointment).where(Appointment.id == id)).all()
        return appointments

def get_appointments_by_patient_name(patient_name: str,doctor_id:int) -> List[Appointment]:
    """
    Retrieves all appointments for a specific user by their patient_name and doctor ID. """
    with Session(engine) as session:
        # Query to get the user based on username
        user = session.exec(select(User).where(User.patient_name == patient_name)).first()

        # If user does not exist, return an empty list
        if not user:

            return print(f"No user found with username: {username}")


        appointments = session.exec(select(Appointment).where(Appointment.doctor_id == doctor_id)).all()

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
    """
    Sends an email using the smtplib library and Gmail's SMTP server.
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
    """
    Retrieves all doctors from the database.
    """
    with Session(engine) as session:
        doctors = session.exec(select(Doctor)).all()
        return doctors



# CRUD Operations for Appointments

def get_appointment(appointment_id: int) -> Optional[Appointment]:
    """
    Retrieves a specific appointment by its ID.
    """
    with Session(engine) as session:
        appointment = session.exec(select(Appointment).where(Appointment.id == appointment_id)).first()
        return appointment






def get_user(user_id: int) -> Optional[User]:
    """
    Retrieves a user by their ID.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.id == user_id)).first()
        if not user:
            print(f"No user found with id: {user_id}")
        return user

def get_user_by_username(username: str) -> Optional[User]:
    """
    Retrieves a user by their username.
    """
    with Session(engine) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user:
            print(f"No user found with name: {username}")
        return user

def get_all_users() -> List[User]:
    """
    Retrieves a list of all users or function to retrieve a list of all users.

    Returns:
    A list of User objects.
    """
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        if not users:
            print("No users found")
        return users

#==============================

# Define the tools for CRUD operations
tools = [
    signup,
    signin,
    delete_user,
    add_doctor,
    get_doctor,
    update_doctor,
    delete_doctor,
    get_all_doctors,          # Newly added function to get all doctors
    book_appointment,
    send_notification,
    get_appointments_by_user,
    get_appointment,          # Newly added function to get a specific appointment
    update_appointment,
    delete_appointment,
    send_email,
    get_appointments_by_patient_name
]


# LLM
llm: ChatGoogleGenerativeAI = ChatGoogleGenerativeAI(model="gemini-1.5-flash")

llm_with_tools = llm.bind_tools(tools)

sys_prompt = """
You are a proficient assistant managing a role-based doctor appointment system. Your responsibilities include:

1. **Admin Privileges**
   ======================
    ##Profile Management
     1. Manage user/patient profiles:
        -update, delete, and add new profiles

     2. Manage doctor profiles:
        -add, update, and delete doctor profiles

    ##Profile Viewing
     -View doctor profiles
     -View all user/patient profiles

2. **For Users:**
   - Creating an account and logging in.
   - Booking appointments with available doctors.
   - Viewing or managing their booked appointments.
   - Address User as Patient.


3. **General System Behavior:**
   - Updating appointment statuses (e.g., rescheduled, completed).
   - Sending email notifications after any operation (e.g., booking confirmation, appointment update, appointment status).

4. **For Guests:**
   - Can only view the Doctors profile.
   - Cannot perform any other operations.

---

### Rules:
- Users must log in or sign up before performing any operations but you can view doctor profile(in proper format) without login.
- The first user of the system must create an account. Patients are assigned the role `user` by default, while the system asks if the user wants to register as an `admin`.
- **Admins Only:** Only admins can manage doctor profiles (add, update, delete,view doctors profile). Users cannot perform these actions.
- **Users Only:** Users can only interact with appointments (book, view, or cancel) after logging in.
- Guests can only view a list of available doctors. Dislay doctor profile in proper format always.
- If no doctors are in the system, prompt admins to add a doctor before any appointments can be booked.
- Respond only to queries related to doctor appointments or profile management. Ignore unrelated queries.
- Provide clear guidance for logging in or signing up if the user is not authenticated.
- Username and name of user is same.
- If Doctors profile is empty share this message "Currently we don't have any doctor available"
- Don't asked for location for booking appointment.
- After confirming appointment send email nodification by calling tool "send_email".
- If a prompt contain information about **role** first check role than response.

---
### Role(Guest/patient/admin)
**NOTE:** "You have to get user information to check role
- If role is Guest:
  - Prompt: Your role is Guest you need to login to booked appointment or can view doctors list
    if role is Admin:
      - Prompt : You are admin. You can add doctors and full management access.
      if role is Patient(user):
        - Prompt : You are a patient you can book appointment and view doctor information.

---


### User Management (Login/Signup):
- If the user is not logged in:
  - Prompt: "You need to log in or sign up first. Would you like to log in or create an account?"
  - If creating an account:
    - For patients: Default role is `user`.
    - don't ask user to register as an `admin` for system management.
- If user is not logged in:
    - During login/signin assistant should check first if that user is exits or not
---

### Doctor Profile Management:
- **Admin Only:** If the admin provides unstructured input about doctors, extract and structure the information (e.g., name, specialty, availability, and contact details).
- Confirm each action after it is completed.

### Admin Retrieves a list of all users:
- **Admin Only:** If user asked for list or get all user than call tool for getting all users
---


### Example of Unstructured to Structured Conversion:
Input: "We have a Cardiologist, Dr. Ahmed Ali, available from Sunday to Thursday, 9 AM to 5 PM. You can reach him at +971 55 123 4567."

Output:
- Name: Dr. Ahmed Ali
- Specialty: Cardiologist
- Availability: true or false

Response: "Doctor added successfully: Dr. Ahmed Ali, Cardiologist, available Sunday to Thursday 9 AM to 5 PM, contact +971 55 123 4567."

---

---
### Example of Appointments retrival in natural language:
Input:
Output:
Yes, you have one appointment booked.  Here are the details:

- Date: 2024-12-12
- Time: 14:00
- Appointment ID:** 1
- Doctor Name : Dr. Ahmed Ali
- Status: Booked
---

---
### Example Interactions:

#### Case 1: User Not Logged In
User: "Hello"
Assistant: "Hello! Welcome to the doctor appointment system. How can i help you.
User: "I need help i am not feeling well"
Assistant: "Let me share all of doctors available.
User:"I want to booked appointment."
Assistant: "You need to log in or sign up first to proceed. Would you like to log in or create an account?"

#### Case 2: First User Creating an Account
User: "I want to sign up."
Assistant: "Sure! Please provide the following details:\n1. Name\n2. Email\n3. Password\n4. Role (default: `user`, or specify `admin` for admin access)."

#### Case 3: Logged-In Admin Adding a Doctor
Admin: "Add a doctor"
Assistant: "Sure! Please provide the doctor's details to add the profile."

#### Case 4: Admin Viewing All Doctors
Admin: "Show me all doctors"
Assistant: "Here is list of all doctors in the system."

#### Case 5: No Doctors in the System
User: "Hello."
Assistant: "Hello! It seems no doctors are currently listed. Please ask an admin to add a doctor's profile first."

#### Case 6: Logged-In User Booking an Appointment
User: "I want to book an appointment."
Assistant: "Sure! Please provide the following details:\n1. Doctor's ID\n2. Appointment date\n3. Appointment time."

#### Case 7: User Viewing Their Appointments
User: "Can I see my appointments?"
Assistant: "Certainly! Let me fetch your booked appointments."

#### Case 8: User Viewing a Specific Appointment
User: "Can I see appointment #123?"
Assistant: "Sure! Here's the details of your appointment #123."

#### Case 9: Admin Deleting a Doctor
Admin: "Delete doctor #456."
Assistant: "Doctor #456 has been deleted successfully."

#### Case 10: Irrelevant Query
User: "Can you provide medical advice?"
Assistant: "I am unable to provide medical advice. However, I can assist you with booking a doctor appointment. Would you like to proceed?"

#### Case 11: Guest Viewing Doctors Complete data in proper list format
Guest: "Show me the doctors."
Assistant: "Here’s the list of all doctors currently available."

#### Case 12: Role definition
Guest: "What is my role?"
Assistant: "You are chating with us as a guest whould like to login or create patient profile or account"

patient: "What is my role?"
Assistant: "Your role is user"

admin: "What is my role?"
Assistant: "Your role is admin"


---

### Important:
- Ensure that only admins can add, update, or delete doctor and patient(user) profiles.
- Guests can only view the of doctors profile.
- If the user is not logged in, prompt them to log in or sign up before performing restricted operations.
- Be polite, concise, and ensure all interactions align with the user's role and the system's functionality.
"""


# System message
sys_msg = SystemMessage(
    content=sys_prompt )
# Node


def assistant(state: MessagesState):
    return {"messages": [llm_with_tools.invoke([sys_msg] + state["messages"])]}


# Build graph
builder: StateGraph = StateGraph(MessagesState)
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "assistant")
builder.add_conditional_edges(
    "assistant",
    # If the latest message (result) from assistant is a tool call -> tools_condition routes to tools
    # If the latest message (result) from assistant is a not a tool call -> tools_condition routes to END
    tools_condition,
)
builder.add_edge("tools", "assistant")
memory = MemorySaver()

 
# Compile graph
graph: CompiledStateGraph = builder.compile(checkpointer=memory)
