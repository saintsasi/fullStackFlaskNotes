from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .models import User, Note, Tag
from . import db
import uuid

auth = Blueprint('auth', __name__)

# -------------------- SIGNUP --------------------
@auth.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('firstName')
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')
        role = request.form.get('role', 'student')

        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists.', category='error')
        elif password1 != password2:
            flash('Passwords do not match.', category='error')
        elif len(password1) < 6:
            flash('Password must be at least 6 characters.', category='error')
        else:
            new_user = User(
                email=email,
                first_name=first_name,
                password=generate_password_hash(password1, method='sha256'),
                role=role,
                is_admin=(role=='admin')
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            flash('Account created successfully!', category='success')
            return redirect(url_for('views.home'))
    return render_template('signup.html')

# -------------------- LOGIN --------------------
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash('Invalid email or password', category='error')
        else:
            login_user(user)
            return redirect(url_for('views.home'))

    return render_template('login.html')

# -------------------- LOGOUT --------------------
@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
