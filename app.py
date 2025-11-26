from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
import qrcode
import io
import base64
from datetime import datetime
import certifi
import urllib.parse
from bson import ObjectId
import re
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# MongoDB Atlas configuration from environment variables
MONGO_URI = os.getenv('MONGODB_URI')

if not MONGO_URI:
    # Fallback to individual components
    username = os.getenv('MONGODB_USERNAME')
    password = os.getenv('MONGODB_PASSWORD')
    cluster_url = os.getenv('MONGODB_CLUSTER_URL')
    database_name = os.getenv('MONGODB_DATABASE', 'qr_code_db')
    
    if all([username, password, cluster_url]):
        MONGO_URI = f"mongodb+srv://{urllib.parse.quote_plus(username)}:{urllib.parse.quote_plus(password)}@{cluster_url}/{database_name}?retryWrites=true&w=majority&tls=true&tlsAllowInvalidCertificates=true"

employees = None

if MONGO_URI:
    try:
        client = MongoClient(
            MONGO_URI,
            tls=True,
            tlsAllowInvalidCertificates=True
        )

        client.admin.command('ping')
        print("✅ Successfully connected to MongoDB Atlas!")

        db = client[database_name if 'database_name' in locals() else 'qr_code_db']
        employees = db['employees']

    except Exception as e:
        print(f"❌ MongoDB connection error: {e}")
        employees = None

# Fallback to JSON storage if MongoDB fails
import json

JSON_DB_FILE = 'employees.json'

def get_employees_collection():
    try:
        if os.path.exists(JSON_DB_FILE):
            with open(JSON_DB_FILE, 'r') as f:
                return json.load(f)
        return []
    except:
        return []

def save_employees_collection(data):
    try:
        with open(JSON_DB_FILE, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except:
        return False

@app.route('/')
def index():
    return render_template('index.html')

def generate_employee_id():
    """Generate unique employee ID"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    import random
    random_suffix = random.randint(100, 999)
    return f"EMP{timestamp}{random_suffix}"

@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    try:
        # Get form data
        name = request.form['name']
        dob = request.form['dob']
        joining_date = request.form['joining_date']
        post = request.form['post']
        department = request.form['department']
        employee_id = request.form.get('employee_id') or generate_employee_id()
        
        # Create employee data
        employee_data = {
            'name': name,
            'dob': dob,
            'joining_date': joining_date,
            'post': post,
            'department': department,
            'employee_id': employee_id,
            'created_at': datetime.now()
        }
        
        # Insert into MongoDB or JSON
        if employees:
            result = employees.insert_one(employee_data.copy())
            record_id = str(result.inserted_id)
        else:
            # JSON fallback
            employees_list = get_employees_collection()
            record_id = f"JSON{datetime.now().strftime('%Y%m%d%H%M%S')}"
            employee_data['_id'] = record_id
            employees_list.append(employee_data)
            save_employees_collection(employees_list)
        
        # Convert for JSON response
        employee_data['_id'] = record_id
        employee_data['created_at'] = employee_data['created_at'].isoformat()

        # Create QR code data (limited information for security)
        qr_data = f"""
Employee Verification:
Name: {name}
Employee ID: {employee_id}
Post: {post}
Department: {department}
Record ID: {record_id}
        """.strip()
        
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert image to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return jsonify({
            'success': True,
            'qr_code': f"data:image/png;base64,{img_str}",
            'employee_data': employee_data,
            'record_id': record_id
        })
        
    except Exception as e:
        print(f"Error generating QR: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/scan_data', methods=['POST'])
def scan_data():
    try:
        scanned_data = request.json.get('data')
        
        # Extract Record ID from scanned text
        lines = scanned_data.split('\n')
        record_id = None
        employee_id = None
        
        for line in lines:
            if line.startswith('Record ID:'):
                record_id = line.split('Record ID:')[1].strip()
            elif line.startswith('Employee ID:'):
                employee_id = line.split('Employee ID:')[1].strip()
        
        employee_data = None
        
        if record_id:
            # Search in MongoDB
            if employees:
                try:
                    if record_id.startswith('JSON'):
                        # JSON record
                        employees_list = get_employees_collection()
                        employee_data = next((emp for emp in employees_list if emp.get('_id') == record_id), None)
                    else:
                        # MongoDB record
                        employee_data = employees.find_one({'_id': ObjectId(record_id)})
                        if employee_data:
                            employee_data['_id'] = str(employee_data['_id'])
                except:
                    pass
        
        # If not found by record_id, try employee_id
        if not employee_data and employee_id:
            if employees:
                try:
                    employee_data = employees.find_one({'employee_id': employee_id})
                    if employee_data:
                        employee_data['_id'] = str(employee_data['_id'])
                except:
                    # JSON fallback
                    employees_list = get_employees_collection()
                    employee_data = next((emp for emp in employees_list if emp.get('employee_id') == employee_id), None)
        
        if employee_data:
            # Convert datetime for JSON
            if 'created_at' in employee_data and not isinstance(employee_data['created_at'], str):
                employee_data['created_at'] = employee_data['created_at'].isoformat()
            
            # Return limited data for security (hide sensitive info)
            secure_data = {
                'name': employee_data.get('name'),
                'employee_id': employee_data.get('employee_id'),
                'post': employee_data.get('post'),
                'department': employee_data.get('department'),
                'joining_date': employee_data.get('joining_date')
            }
            
            return jsonify({
                'success': True,
                'employee_data': secure_data,
                'scanned_data': scanned_data
            })
        
        # If no record found
        return jsonify({
            'success': True,
            'scanned_data': scanned_data,
            'employee_data': None
        })
        
    except Exception as e:
        print(f"Error scanning data: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_records', methods=['GET'])
def get_records():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 5))
        search = request.args.get('search', '')
        filter_by = request.args.get('filter_by', 'all')
        
        skip = (page - 1) * per_page
        
        if employees:
            # MongoDB query with search and filter
            query = {}
            if search:
                if filter_by == 'name':
                    query['name'] = {'$regex': search, '$options': 'i'}
                elif filter_by == 'employee_id':
                    query['employee_id'] = {'$regex': search, '$options': 'i'}
                elif filter_by == 'department':
                    query['department'] = {'$regex': search, '$options': 'i'}
                elif filter_by == 'post':
                    query['post'] = {'$regex': search, '$options': 'i'}
                else:  # all fields
                    query['$or'] = [
                        {'name': {'$regex': search, '$options': 'i'}},
                        {'employee_id': {'$regex': search, '$options': 'i'}},
                        {'department': {'$regex': search, '$options': 'i'}},
                        {'post': {'$regex': search, '$options': 'i'}}
                    ]
            
            total = employees.count_documents(query)
            all_employees = list(employees.find(query)
                                          .sort('created_at', -1)
                                          .skip(skip)
                                          .limit(per_page))
            
            # Convert for JSON
            for emp in all_employees:
                emp['_id'] = str(emp['_id'])
                if 'created_at' in emp:
                    emp['created_at'] = emp['created_at'].isoformat()
        else:
            # JSON fallback
            employees_list = get_employees_collection()
            
            # Apply search filter
            if search:
                search_lower = search.lower()
                employees_list = [emp for emp in employees_list if (
                    search_lower in emp.get('name', '').lower() or
                    search_lower in emp.get('employee_id', '').lower() or
                    search_lower in emp.get('department', '').lower() or
                    search_lower in emp.get('post', '').lower()
                )]
            
            total = len(employees_list)
            # Sort by created_at (newest first)
            employees_list.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            all_employees = employees_list[skip:skip + per_page]

        total_pages = (total + per_page - 1) // per_page
        
        return jsonify({
            'success': True, 
            'employees': all_employees,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })

    except Exception as e:
        print(f"Error getting records: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/search_employee', methods=['GET'])
def search_employee():
    try:
        query = request.args.get('q', '')
        field = request.args.get('field', 'all')
        
        if not query:
            return jsonify({'success': True, 'results': []})
        
        results = []
        
        if employees:
            # MongoDB search
            search_query = {}
            if field == 'name':
                search_query['name'] = {'$regex': query, '$options': 'i'}
            elif field == 'employee_id':
                search_query['employee_id'] = {'$regex': query, '$options': 'i'}
            else:
                search_query['$or'] = [
                    {'name': {'$regex': query, '$options': 'i'}},
                    {'employee_id': {'$regex': query, '$options': 'i'}},
                    {'department': {'$regex': query, '$options': 'i'}},
                    {'post': {'$regex': query, '$options': 'i'}}
                ]
            
            results = list(employees.find(search_query)
                                   .sort('created_at', -1)
                                   .limit(10))
            
            for emp in results:
                emp['_id'] = str(emp['_id'])
                if 'created_at' in emp:
                    emp['created_at'] = emp['created_at'].isoformat()
        else:
            # JSON fallback search
            employees_list = get_employees_collection()
            query_lower = query.lower()
            
            for emp in employees_list:
                if (field == 'name' and query_lower in emp.get('name', '').lower()) or \
                   (field == 'employee_id' and query_lower in emp.get('employee_id', '').lower()) or \
                   (field == 'all' and (
                       query_lower in emp.get('name', '').lower() or
                       query_lower in emp.get('employee_id', '').lower() or
                       query_lower in emp.get('department', '').lower() or
                       query_lower in emp.get('post', '').lower()
                   )):
                    results.append(emp)
                    if len(results) >= 10:
                        break
        
        return jsonify({'success': True, 'results': results})
        
    except Exception as e:
        print(f"Error searching employee: {e}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)