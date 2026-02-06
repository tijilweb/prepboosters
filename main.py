from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///prepboosters.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==================== DATABASE MODELS ====================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    profile_image = db.Column(db.String(200), default='default.png')
    last_active = db.Column(db.DateTime, default=datetime.utcnow)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    icon = db.Column(db.String(100), default='book')
    
class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    google_drive_link = db.Column(db.String(500), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    thumbnail = db.Column(db.String(200), default='book_placeholder.png')
    
    category = db.relationship('Category', backref=db.backref('books', lazy=True))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('messages', lazy=True))

class WebsiteSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)

# ==================== HELPER FUNCTIONS ====================
def get_setting(key, default=None):
    setting = WebsiteSetting.query.filter_by(key=key).first()
    return setting.value if setting else default

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Admin access required', 'danger')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== REQUEST HANDLERS ====================
@app.before_request
def update_user_activity():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.last_active = datetime.utcnow()
            db.session.commit()

@app.context_processor
def inject_settings():
    def get_setting_context(key, default=None):
        return get_setting(key, default)
    return dict(get_setting=get_setting_context)

# ==================== PUBLIC ROUTES ====================
@app.route('/')
def home():
    categories = Category.query.all()
    return render_template('index.html', categories=categories)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            user.last_active = datetime.utcnow()
            db.session.commit()
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if get_setting('registration_open', '1') == '0':
        flash('Registration is currently closed', 'danger')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already taken', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            password=hashed_password,
            is_admin=False
        )
        
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully', 'success')
    return redirect(url_for('home'))

@app.route('/category/<int:category_id>')
def category_books(category_id):
    category = Category.query.get_or_404(category_id)
    books = Book.query.filter_by(category_id=category_id, is_active=True).all()
    return render_template('category.html', category=category, books=books)

@app.route('/chat')
@login_required
def chat():
    if get_setting('chat_enabled', '1') == '0':
        flash('Chat system is currently disabled', 'warning')
        return redirect(url_for('home'))
    
    max_messages = int(get_setting('chat_max_messages', '100'))
    messages = Message.query.order_by(Message.created_at.desc()).limit(max_messages).all()
    messages.reverse()
    return render_template('chat.html', messages=messages)

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    if get_setting('chat_enabled', '1') == '0':
        flash('Chat system is currently disabled', 'danger')
        return redirect(url_for('chat'))
    
    content = request.form['content'].strip()
    max_length = int(get_setting('chat_max_length', '500'))
    
    if len(content) > max_length:
        flash(f'Message too long (max {max_length} characters)', 'danger')
    elif content:
        message = Message(
            content=content,
            user_id=session['user_id']
        )
        db.session.add(message)
        db.session.commit()
        flash('Message sent!', 'success')
    else:
        flash('Message cannot be empty', 'warning')
    
    return redirect(url_for('chat'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy.html')

# ==================== ADMIN ROUTES ====================
@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = {
        'total_users': User.query.count(),
        'total_books': Book.query.count(),
        'total_categories': Category.query.count(),
        'total_messages': Message.query.count(),
        'total_admins': User.query.filter_by(is_admin=True).count(),
        'recent_users': User.query.filter(
            User.created_at >= datetime.utcnow() - timedelta(days=7)
        ).count(),
        'recent_books': Book.query.filter(
            Book.uploaded_at >= datetime.utcnow() - timedelta(days=7)
        ).count(),
        'admin_percentage': (User.query.filter_by(is_admin=True).count() / User.query.count() * 100) if User.query.count() > 0 else 0
    }
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/categories')
@admin_required
def admin_categories():
    categories = Category.query.all()
    return render_template('admin/categories.html', categories=categories)

@app.route('/admin/categories/add', methods=['POST'])
@admin_required
def add_category():
    name = request.form['name']
    description = request.form['description']
    icon = request.form.get('icon', 'book')
    
    category = Category(name=name, description=description, icon=icon)
    db.session.add(category)
    db.session.commit()
    flash('Category added successfully', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/edit/<int:category_id>', methods=['POST'])
@admin_required
def edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    category.name = request.form['name']
    category.description = request.form['description']
    category.icon = request.form['icon']
    db.session.commit()
    flash('Category updated successfully', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/categories/delete/<int:category_id>')
@admin_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash('Category deleted successfully', 'success')
    return redirect(url_for('admin_categories'))

@app.route('/admin/books')
@admin_required
def admin_books():
    books = Book.query.all()
    categories = Category.query.all()
    return render_template('admin/books.html', books=books, categories=categories)

@app.route('/admin/books/add', methods=['POST'])
@admin_required
def add_book():
    title = request.form['title']
    description = request.form['description']
    google_drive_link = request.form['google_drive_link']
    category_id = request.form['category_id']
    thumbnail = request.form.get('thumbnail', 'book_placeholder.png')
    
    book = Book(
        title=title,
        description=description,
        google_drive_link=google_drive_link,
        category_id=category_id,
        uploaded_by=session['user_id'],
        thumbnail=thumbnail
    )
    
    db.session.add(book)
    db.session.commit()
    flash('Book added successfully', 'success')
    return redirect(url_for('admin_books'))

@app.route('/admin/books/edit/<int:book_id>', methods=['POST'])
@admin_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    book.title = request.form['title']
    book.description = request.form['description']
    book.google_drive_link = request.form['google_drive_link']
    book.category_id = request.form['category_id']
    book.is_active = 'is_active' in request.form
    db.session.commit()
    flash('Book updated successfully', 'success')
    return redirect(url_for('admin_books'))

@app.route('/admin/books/delete/<int:book_id>')
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    book.is_active = False
    db.session.commit()
    flash('Book deactivated successfully', 'success')
    return redirect(url_for('admin_books'))

@app.route('/admin/settings')
@admin_required
def admin_settings():
    return render_template('admin/settings.html')

@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def update_settings():
    for key in request.form:
        if key.startswith('setting_'):
            setting_key = key.replace('setting_', '')
            setting = WebsiteSetting.query.filter_by(key=setting_key).first()
            if setting:
                setting.value = request.form[key]
            else:
                setting = WebsiteSetting(key=setting_key, value=request.form[key])
                db.session.add(setting)
    db.session.commit()
    flash('Settings updated successfully', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/reset')
@admin_required
def reset_settings():
    WebsiteSetting.query.delete()
    db.session.commit()
    
    default_settings = [
        ('website_name', 'PrepBoosters'),
        ('contact_email', 'support@prepboosters.com'),
        ('contact_phone', '+91 98765 43210'),
        ('website_description', 'Your exam preparation partner for JEE, NEET, and Class 10th'),
        ('registration_open', '1'),
        ('maintenance_mode', '0'),
        ('chat_enabled', '1'),
        ('chat_room_name', 'PrepBoosters Community'),
        ('chat_welcome', 'Welcome to PrepBoosters Community Chat!'),
        ('chat_max_messages', '100'),
        ('chat_max_length', '500'),
        ('chat_guest_view', '0'),
        ('meta_title', 'PrepBoosters - Exam Preparation Platform'),
        ('meta_description', 'Free study materials for JEE, NEET, and Class 10th exams'),
        ('meta_keywords', 'JEE, NEET, Class 10th, exam preparation')
    ]
    
    for key, value in default_settings:
        setting = WebsiteSetting(key=key, value=value)
        db.session.add(setting)
    
    db.session.commit()
    flash('Settings reset to default values', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/clear_chat')
@admin_required
def clear_chat():
    Message.query.delete()
    db.session.commit()
    flash('All chat messages cleared', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.all()
    recent_users = User.query.filter(
        User.created_at >= datetime.utcnow() - timedelta(days=1)
    ).count()
    total_messages = Message.query.count()
    return render_template('admin/users.html', 
                          users=users, 
                          recent_users=recent_users,
                          total_messages=total_messages)

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def add_user():
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']
    confirm_password = request.form['confirm_password']
    is_admin = request.form.get('is_admin') == '1'
    
    if User.query.filter_by(username=username).first():
        flash('Username already exists', 'danger')
        return redirect(url_for('admin_users'))
    
    if User.query.filter_by(email=email).first():
        flash('Email already registered', 'danger')
        return redirect(url_for('admin_users'))
    
    if password != confirm_password:
        flash('Passwords do not match', 'danger')
        return redirect(url_for('admin_users'))
    
    hashed_password = generate_password_hash(password)
    new_user = User(
        username=username,
        email=email,
        password=hashed_password,
        is_admin=is_admin
    )
    
    db.session.add(new_user)
    db.session.commit()
    flash(f'User {username} added successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/edit/<int:user_id>', methods=['POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    user.email = request.form['email']
    user.is_admin = request.form.get('is_admin') == '1'
    db.session.commit()
    flash('User updated successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/reset_password/<int:user_id>', methods=['POST'])
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form['new_password']
    confirm_password = request.form['confirm_password']
    
    if new_password != confirm_password:
        flash('Passwords do not match', 'danger')
        return redirect(url_for('admin_users'))
    
    user.password = generate_password_hash(new_password)
    db.session.commit()
    flash(f'Password reset for {user.username}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/make_admin/<int:user_id>')
@admin_required
def make_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash('Cannot change your own admin status', 'warning')
        return redirect(url_for('admin_users'))
    user.is_admin = True
    db.session.commit()
    flash(f'{user.username} is now an administrator', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/remove_admin/<int:user_id>')
@admin_required
def remove_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash('Cannot remove your own admin privileges', 'warning')
        return redirect(url_for('admin_users'))
    
    admin_count = User.query.filter_by(is_admin=True).count()
    if admin_count <= 1:
        flash('Cannot remove the last administrator', 'danger')
        return redirect(url_for('admin_users'))
    
    user.is_admin = False
    db.session.commit()
    flash(f'{user.username} is no longer an administrator', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<int:user_id>')
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash('Cannot delete your own account', 'warning')
        return redirect(url_for('admin_users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'User {user.username} deleted successfully', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/backup')
@admin_required
def backup_database():
    import shutil
    import datetime as dt
    
    backup_file = f"backup_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2('prepboosters.db', backup_file)
    
    flash(f'Database backed up as {backup_file}', 'success')
    return redirect(url_for('admin_settings'))

# ==================== API ROUTES ====================
@app.route('/api/check_username/<username>')
def check_username(username):
    user = User.query.filter_by(username=username).first()
    return jsonify({'available': user is None})

@app.route('/api/user_stats')
@admin_required
def user_stats():
    total = User.query.count()
    today = User.query.filter(
        User.created_at >= datetime.utcnow().date()
    ).count()
    admins = User.query.filter_by(is_admin=True).count()
    
    return jsonify({
        'total': total,
        'today': today,
        'admins': admins
    })

@app.route('/api/chat_messages')
@login_required
def chat_messages():
    if get_setting('chat_enabled', '1') == '0':
        return jsonify({'error': 'Chat disabled'}), 403
    
    max_messages = int(get_setting('chat_max_messages', '100'))
    messages = Message.query.order_by(Message.created_at.asc()).limit(max_messages).all()
    
    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'content': msg.content,
            'username': msg.user.username,
            'user_id': msg.user_id,
            'created_at': msg.created_at.strftime('%H:%M'),
            'is_current_user': msg.user_id == session['user_id']
        })
    
    return jsonify({'messages': messages_data})

@app.route('/api/online_users')
@login_required
def online_users():
    five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
    online_users_list = User.query.filter(
        User.last_active >= five_minutes_ago
    ).order_by(User.last_active.desc()).all()
    
    today = datetime.utcnow().date()
    active_today = User.query.filter(
        User.last_active >= datetime.combine(today, datetime.min.time())
    ).count()
    
    users_data = []
    for user in online_users_list:
        mins_ago = (datetime.utcnow() - user.last_active).seconds // 60
        
        if mins_ago < 1:
            status = "Just now"
        elif mins_ago < 5:
            status = f"{mins_ago} min ago"
        else:
            status = "Online"
        
        users_data.append({
            'id': user.id,
            'username': user.username,
            'status': status,
            'last_active': user.last_active.isoformat()
        })
    
    return jsonify({
        'users': users_data,
        'online_count': len(online_users_list),
        'active_users': active_today
    })

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('403.html'), 403

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# ==================== INITIALIZATION ====================
def initialize_database():
    with app.app_context():
        db.create_all()
        
        # Create default categories
        if Category.query.count() == 0:
            default_categories = [
                Category(name='JEE', description='Engineering Entrance Exam Preparation', icon='calculator'),
                Category(name='NEET', description='Medical Entrance Exam Preparation', icon='activity'),
                Category(name='Class 10th', description='Class 10th Board Preparation', icon='book-open')
            ]
            for category in default_categories:
                db.session.add(category)
        
        # Create default admin user
        if not User.query.filter_by(username='admin').first():
            admin_user = User(
                username='admin',
                email='admin@prepboosters.com',
                password=generate_password_hash('admin123'),
                is_admin=True
            )
            db.session.add(admin_user)
        
        # Create default settings
        if WebsiteSetting.query.count() == 0:
            default_settings = [
                ('website_name', 'PrepBoosters'),
                ('contact_email', 'support@prepboosters.com'),
                ('contact_phone', '+91 98765 43210'),
                ('website_description', 'Your exam preparation partner for JEE, NEET, and Class 10th'),
                ('registration_open', '1'),
                ('maintenance_mode', '0'),
                ('chat_enabled', '1'),
                ('chat_room_name', 'PrepBoosters Community'),
                ('chat_welcome', 'Welcome to PrepBoosters Community Chat! Be respectful and help each other.'),
                ('chat_max_messages', '100'),
                ('chat_max_length', '500'),
                ('chat_guest_view', '0'),
                ('meta_title', 'PrepBoosters - Exam Preparation Platform'),
                ('meta_description', 'Free study materials for JEE, NEET, and Class 10th exams. Google Drive links, community chat, and more.'),
                ('meta_keywords', 'JEE preparation, NEET preparation, Class 10th, exam preparation, study materials'),
                ('default_role', 'student')
            ]
            
            for key, value in default_settings:
                setting = WebsiteSetting(key=key, value=value)
                db.session.add(setting)
        
        db.session.commit()
        print("✅ Database initialized successfully!")

# ==================== MAIN EXECUTION ====================
if __name__ == '__main__':
    # Create templates directory
    if not os.path.exists('templates'):
        os.makedirs('templates')
        print("✅ Created templates directory")
    
    # Create admin directory
    admin_dir = os.path.join('templates', 'admin')
    if not os.path.exists(admin_dir):
        os.makedirs(admin_dir)
        print("✅ Created admin templates directory")
    
    # Create error pages
    error_templates = {
        '404.html': '''{% extends "base.html" %}
{% block title %}404 - Page Not Found{% endblock %}
{% block content %}
<div class="container py-5">
    <div class="text-center">
        <h1 class="display-1 text-muted">404</h1>
        <h2 class="mb-4">Page Not Found</h2>
        <p class="lead mb-4">The page you are looking for does not exist.</p>
        <a href="{{ url_for('home') }}" class="btn btn-primary">
            <i class="bi bi-house"></i> Go Home
        </a>
    </div>
</div>
{% endblock %}''',
        '403.html': '''{% extends "base.html" %}
{% block title %}403 - Forbidden{% endblock %}
{% block content %}
<div class="container py-5">
    <div class="text-center">
        <h1 class="display-1 text-muted">403</h1>
        <h2 class="mb-4">Access Forbidden</h2>
        <p class="lead mb-4">You don't have permission to access this page.</p>
        <a href="{{ url_for('home') }}" class="btn btn-primary">
            <i class="bi bi-house"></i> Go Home
        </a>
    </div>
</div>
{% endblock %}''',
        '500.html': '''{% extends "base.html" %}
{% block title %}500 - Server Error{% endblock %}
{% block content %}
<div class="container py-5">
    <div class="text-center">
        <h1 class="display-1 text-muted">500</h1>
        <h2 class="mb-4">Internal Server Error</h2>
        <p class="lead mb-4">Something went wrong on our end. Please try again later.</p>
        <a href="{{ url_for('home') }}" class="btn btn-primary">
            <i class="bi bi-house"></i> Go Home
        </a>
    </div>
</div>
{% endblock %}'''
    }
    
    for filename, content in error_templates.items():
        filepath = os.path.join('templates', filename)
        if not os.path.exists(filepath):
            with open(filepath, 'w') as f:
                f.write(content)
            print(f"✅ Created {filename}")
    
    # Initialize database
    initialize_database()
    
    print("\n" + "="*50)
    print("🚀 PrepBoosters Website Started!")
    print("="*50)
    print("🌐 Access: http://localhost:5000")
    print("🔑 Admin: username='admin', password='admin123'")
    print("="*50 + "\n")
    
    app.run(debug=True, port=5000)
