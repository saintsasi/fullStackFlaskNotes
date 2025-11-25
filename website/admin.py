from flask import Blueprint, render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
from .models import User, Note
from . import db

admin = Blueprint('admin', __name__)

# -------------------- ADMIN DECORATOR --------------------
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('Access Denied: Administrators only.', category='error')
            return redirect(url_for('views.home'))
        return f(*args, **kwargs)
    return decorated

# -------------------- DASHBOARD --------------------
@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    all_users = User.query.all()
    total_notes = Note.query.count()
    return render_template('admin_dashboard.html', users=all_users, total_notes=total_notes)

# -------------------- DELETE USER --------------------
@admin.route('/delete-user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.is_admin:
        flash("Cannot delete an administrator account.", category='error')
        return redirect(url_for('admin.dashboard'))

    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f'User {user_to_delete.email} successfully deleted.', category='success')
    return redirect(url_for('admin.dashboard'))
