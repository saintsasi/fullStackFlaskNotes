from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_from_directory
from flask_login import login_required, current_user
from sqlalchemy import func
from datetime import datetime
from werkzeug.utils import secure_filename
import os
from .models import Note, Tag, ClassRoom, ClassPost, Message, User, Comment, Reaction, ClassChatMessage, Poll, PollOption, PollVote, NoteAttachment
from . import db
import uuid
import json

views = Blueprint('views', __name__)


# --------- Helpers ---------

def dm_room_id(user1_id: int, user2_id: int) -> str:
    """Stable room ID for a pair of users."""
    a, b = sorted([user1_id, user2_id])
    return f"dm_{a}_{b}"


# --------- Context processor: unread messages badge ---------

@views.app_context_processor
def inject_unread_message_count():
    if current_user.is_authenticated:
        count = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    else:
        count = 0
    return {'unread_messages': count}


def _emit_unread_count(user_id: int):
    """Broadcast unread count to a user's personal room."""
    count = Message.query.filter_by(receiver_id=user_id, is_read=False).count()
    return count


# --------- HOME: latest class notes feed ---------

@views.route('/')
@login_required
def home():
    # Collect posts from classes the user joined
    class_notes = []
    for classroom in current_user.joined_classes:
        class_notes.extend(classroom.posts)

    # Also include posts for classes where the user is teacher
    teacher_classes = ClassRoom.query.filter_by(teacher_id=current_user.id).all()
    for classroom in teacher_classes:
        if classroom not in current_user.joined_classes:
            class_notes.extend(classroom.posts)

    class_notes = sorted(
        class_notes,
        key=lambda p: p.timestamp or datetime.min,
        reverse=True
    )
    return render_template('home.html', feed_notes=class_notes, user=current_user)


# --------- MY NOTES ---------

@views.route('/my-notes')
@login_required
def my_notes():
    notes = Note.query.filter_by(user_id=current_user.id).order_by(Note.date.desc()).all()
    return render_template('my_notes.html', user_notes=notes, user=current_user)


# --------- CREATE NOTE ---------

@views.route('/create-note', methods=['GET', 'POST'])
@login_required
def create_note():
    if request.method == 'POST':
        data = request.form.get('note')
        title = request.form.get('title', 'Untitled')
        tags_list = request.form.get('tags', '').split(',')
        is_public = bool(request.form.get('is_public'))
        pinned = bool(request.form.get('pinned'))
        upload = request.files.get('attachment')

        if not data or len(data.strip()) < 1:
            flash('Note is too short', category='danger')
        else:
            new_note = Note(
                title=title,
                content=data,
                user_id=current_user.id,
                share_link=str(uuid.uuid4())[:8],
                is_public=is_public,
                pinned=pinned
            )

            for t in tags_list:
                t = t.strip()
                if t:
                    tag = Tag.query.filter_by(name=t).first()
                    if not tag:
                        tag = Tag(name=t)
                        db.session.add(tag)
                    new_note.tags.append(tag)

            db.session.add(new_note)
            db.session.commit()

            if upload and upload.filename:
                _save_note_attachment(new_note, upload)
                db.session.commit()
            flash('Note created successfully', category='success')
            return redirect(url_for('views.my_notes'))

    return render_template('create_note.html', user=current_user)

# -------------------- VIEW NOTE PAGE --------------------
@views.route('/note/<int:note_id>')
@login_required
def view_note(note_id):
    note = Note.query.get_or_404(note_id)

    # Only owner or public can view
    if note.user_id != current_user.id and not note.is_public:
        flash("You don't have access to this note.", "error")
        return redirect(url_for("views.my_notes"))

    comments = Comment.query.filter_by(note_id=note.id, parent_id=None).order_by(Comment.timestamp.asc()).all()
    return render_template("view_note.html", note=note, comments=comments)

# ----------------------------------------------------
# EDIT NOTE PAGE  (GET shows form, POST saves changes)
# ----------------------------------------------------
@views.route('/edit-note/<int:note_id>', methods=['GET', 'POST'])
@login_required
def edit_note_page(note_id):
    note = Note.query.get_or_404(note_id)

    # Only the note owner can edit
    if note.user_id != current_user.id:
        flash("You do not have permission to edit this note.", "error")
        return redirect(url_for('views.my_notes'))

    if request.method == "POST":
        note.title = request.form.get("title")
        note.content = request.form.get("content")
        note.is_public = bool(request.form.get("is_public"))
        upload = request.files.get('attachment')

        if upload and upload.filename:
            _save_note_attachment(note, upload)

        db.session.commit()
        flash("Note updated successfully!", "success")
        return redirect(url_for('views.my_notes'))

    return render_template("edit_note.html", note=note)


# --------- COMMENTS API ---------

@views.route('/add-comment', methods=['POST'])
@login_required
def add_comment():
    data = request.get_json() or {}
    note_id = data.get('noteId')
    content = (data.get('content') or '').strip()
    parent_id = data.get('parentId')

    if not note_id or not content:
        return jsonify(success=False, error="Missing note or content"), 400

    note = Note.query.get(note_id)
    if not note:
        return jsonify(success=False, error="Note not found"), 404

    # Only owner or public notes can be commented
    if note.user_id != current_user.id and not note.is_public:
        return jsonify(success=False, error="Not allowed"), 403

    parent_comment = None
    if parent_id:
        parent_comment = Comment.query.get(parent_id)
        if not parent_comment or parent_comment.note_id != note.id:
            return jsonify(success=False, error="Invalid parent comment"), 400

    new_comment = Comment(
        note_id=note.id,
        user_id=current_user.id,
        parent_id=parent_id,
        content=content
    )
    db.session.add(new_comment)
    db.session.commit()

    return jsonify(
        success=True,
        author_name=current_user.first_name or current_user.email,
        timestamp=new_comment.timestamp.strftime('%Y-%m-%d %H:%M')
    )


# --------- REACTIONS API ---------

@views.route('/add-reaction', methods=['POST'])
@login_required
def add_reaction():
    data = request.get_json() or {}
    note_id = data.get('noteId')
    reaction_type = data.get('type')

    if reaction_type not in ('like', 'dislike'):
        return jsonify(success=False, error="Invalid reaction"), 400

    note = Note.query.get(note_id)
    if not note:
        return jsonify(success=False, error="Note not found"), 404

    if note.user_id != current_user.id and not note.is_public:
        return jsonify(success=False, error="Not allowed"), 403

    existing = Reaction.query.filter_by(user_id=current_user.id, note_id=note.id).first()
    if existing:
        existing.type = reaction_type
    else:
        db.session.add(Reaction(user_id=current_user.id, note_id=note.id, type=reaction_type))

    db.session.commit()

    counts = {
        'likes': Reaction.query.filter_by(note_id=note.id, type='like').count(),
        'dislikes': Reaction.query.filter_by(note_id=note.id, type='dislike').count(),
    }
    return jsonify(success=True, counts=counts)




# --------- CLASSES LIST ---------

@views.route('/classes')
@login_required
def classes():
    # joined or taught classes
    joined = current_user.joined_classes
    teaching = ClassRoom.query.filter_by(teacher_id=current_user.id).all()
    return render_template('classes.html', joined=joined, teaching=teaching, user=current_user)


# --------- CLASS FEED ---------

@views.route('/class/<int:class_id>')
@login_required
def class_feed(class_id):
    classroom = ClassRoom.query.get_or_404(class_id)
    if (current_user not in classroom.students) and (current_user.id != classroom.teacher_id) and (not current_user.is_admin):
        flash('Access Denied to this class', category='danger')
        return redirect(url_for('views.home'))

    posts = sorted(classroom.posts, key=lambda p: p.timestamp or datetime.min, reverse=True)
    return render_template('class_feed.html', classroom=classroom, user=current_user, posts=posts)


@views.route('/class/<int:class_id>/chat')
@login_required
def class_chat(class_id):
    classroom = ClassRoom.query.get_or_404(class_id)
    if (current_user not in classroom.students) and (current_user.id != classroom.teacher_id) and (not current_user.is_admin):
        flash('Access Denied to this class', category='danger')
        return redirect(url_for('views.home'))

    chat_messages = ClassChatMessage.query.filter_by(classroom_id=classroom.id)\
        .order_by(ClassChatMessage.timestamp.asc()).limit(200).all()
    polls = Poll.query.filter_by(classroom_id=classroom.id).order_by(Poll.timestamp.desc()).limit(10).all()

    return render_template(
        'class_chat.html',
        classroom=classroom,
        chat_messages=chat_messages,
        polls=polls,
        user=current_user
    )


# --------- MESSAGES INDEX: list of users ---------

@views.route('/messages', methods=['GET'])
@login_required
def messages_index():
    users = User.query.filter(User.id != current_user.id).order_by(User.first_name.asc()).all()
    return render_template('messages_index.html', users=users, user=current_user)


# --------- MESSAGES PAGE: chat with specific user ---------

@views.route('/messages/<int:user_id>', methods=['GET'])
@login_required
def messages(user_id):
    other_user = User.query.get_or_404(user_id)

    # sidebar list with unread counts
    sidebar_users = User.query.filter(User.id != current_user.id).order_by(User.first_name.asc()).all()
    unread_rows = (
        db.session.query(Message.sender_id, func.count(Message.id))
        .filter(Message.receiver_id == current_user.id, Message.is_read.is_(False))
        .group_by(Message.sender_id)
        .all()
    )
    unread_map = {sid: count for sid, count in unread_rows}

    # load last 50 messages between both users
    msgs_query = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user.id)) |
        ((Message.sender_id == other_user.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.desc()).limit(50).all()
    msgs = list(reversed(msgs_query))  # show newest while keeping chronological order

    # mark messages to current_user as read
    changed = False
    for m in msgs:
        if m.receiver_id == current_user.id and not m.is_read:
            m.is_read = True
            changed = True
    if changed:
        db.session.commit()

    return render_template(
        'messages.html',
        messages=msgs,
        other_user=other_user,
        user=current_user,
        sidebar_users=sidebar_users,
        unread_map=unread_map
    )


@views.route('/messages/<int:user_id>/send', methods=['POST'])
@login_required
def messages_send(user_id):
    """HTTP fallback to send a DM (used if socket not connected)."""
    other_user = User.query.get_or_404(user_id)
    content = (request.json or {}).get('content', '').strip()
    if not content:
        return jsonify(success=False, error="Message is empty"), 400

    msg = Message(
        sender_id=current_user.id,
        receiver_id=other_user.id,
        content=content,
        is_read=False
    )
    db.session.add(msg)
    db.session.commit()

    return jsonify(
        success=True,
        message={
            'id': msg.id,
            'sender_id': msg.sender_id,
            'receiver_id': msg.receiver_id,
            'content': msg.content,
            'timestamp': msg.timestamp.strftime('%Y-%m-%d %H:%M'),
        }
    )


@views.route('/messages/<int:user_id>/feed', methods=['GET'])
@login_required
def messages_feed(user_id):
    """HTTP pollable feed of last 50 messages between users."""
    other_user = User.query.get_or_404(user_id)
    after_id = request.args.get('after', type=int)
    msgs_query = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user.id)) |
        ((Message.sender_id == other_user.id) & (Message.receiver_id == current_user.id))
    )
    if after_id:
        msgs_query = msgs_query.filter(Message.id > after_id)

    msgs_query = msgs_query.order_by(Message.timestamp.asc()).limit(200).all()
    msgs = list(msgs_query)
    return jsonify([{
        'id': m.id,
        'sender_id': m.sender_id,
        'receiver_id': m.receiver_id,
        'content': m.content,
        'timestamp': m.timestamp.strftime('%Y-%m-%d %H:%M'),
    } for m in msgs])


# --------- CLASS CHAT API ---------

def _classroom_access_or_403(classroom_id):
    classroom = ClassRoom.query.get_or_404(classroom_id)
    if (current_user not in classroom.students) and (current_user.id != classroom.teacher_id) and (not current_user.is_admin):
        return None
    return classroom


def _save_note_attachment(note: Note, upload):
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'doc', 'docx'}
    filename = secure_filename(upload.filename)
    if not filename:
        return
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in allowed:
        flash('File type not allowed', 'danger')
        return

    upload_dir = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, '..', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    dest = os.path.join(upload_dir, unique_name)
    upload.save(dest)

    attach = NoteAttachment(
        note_id=note.id,
        filename=filename,
        filepath=unique_name,
        mimetype=upload.mimetype,
        size=os.path.getsize(dest)
    )
    db.session.add(attach)


@views.route('/class/join', methods=['POST'])
@login_required
def join_class_by_code():
    code = (request.form.get('code') or '').strip()
    classroom = ClassRoom.query.filter_by(code=code).first()
    if not classroom:
        flash('Invalid class code', 'danger')
        return redirect(url_for('views.classes'))
    if current_user not in classroom.students:
        classroom.students.append(current_user)
        db.session.commit()
        flash(f'Joined {classroom.name}', 'success')
    else:
        flash('You are already in this class.', 'info')
    return redirect(url_for('views.class_feed', class_id=classroom.id))


@views.route('/class/<int:class_id>/remove-student/<int:user_id>', methods=['POST'])
@login_required
def remove_student(class_id, user_id):
    classroom = ClassRoom.query.get_or_404(class_id)
    if (current_user.id != classroom.teacher_id) and (not current_user.is_admin):
        flash('Only teacher or admin can remove students', 'danger')
        return redirect(url_for('views.class_feed', class_id=class_id))
    student = User.query.get_or_404(user_id)
    if student in classroom.students:
        classroom.students.remove(student)
        db.session.commit()
        flash(f'Removed {student.first_name or student.email}', 'success')
    return redirect(url_for('views.class_feed', class_id=class_id))


@views.route('/class/<int:class_id>/chat/send', methods=['POST'])
@login_required
def class_chat_send(class_id):
    classroom = _classroom_access_or_403(class_id)
    if not classroom:
        return jsonify(success=False, error="Access denied"), 403
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify(success=False, error="Message empty"), 400

    msg = ClassChatMessage(classroom_id=classroom.id, user_id=current_user.id, content=content)
    db.session.add(msg)
    db.session.commit()

    return jsonify(success=True, message={
        'id': msg.id,
        'user_id': msg.user_id,
        'content': msg.content,
        'timestamp': msg.timestamp.strftime('%Y-%m-%d %H:%M'),
        'author': current_user.first_name or current_user.email
    })


@views.route('/class/<int:class_id>/chat/feed')
@login_required
def class_chat_feed(class_id):
    classroom = _classroom_access_or_403(class_id)
    if not classroom:
        return jsonify([]), 403
    after_id = request.args.get('after', type=int)
    qs = ClassChatMessage.query.filter_by(classroom_id=classroom.id)
    if after_id:
        qs = qs.filter(ClassChatMessage.id > after_id)
    msgs = qs.order_by(ClassChatMessage.timestamp.asc()).limit(200).all()
    return jsonify([{
        'id': m.id,
        'user_id': m.user_id,
        'author': m.user.first_name or m.user.email,
        'content': m.content,
        'timestamp': m.timestamp.strftime('%Y-%m-%d %H:%M'),
    } for m in msgs])


@views.route('/class/<int:class_id>/polls', methods=['POST'])
@login_required
def class_create_poll(class_id):
    classroom = _classroom_access_or_403(class_id)
    if not classroom:
        return jsonify(success=False, error="Access denied"), 403
    if (current_user.id != classroom.teacher_id) and (not current_user.is_admin):
        return jsonify(success=False, error="Only teacher/admin can create polls"), 403

    data = request.get_json() or {}
    question = (data.get('question') or '').strip()
    options = data.get('options') or []
    options = [o.strip() for o in options if o and o.strip()]

    if not question or len(options) < 2:
        return jsonify(success=False, error="Question and at least 2 options required"), 400

    poll = Poll(question=question, classroom_id=classroom.id, created_by=current_user.id)
    db.session.add(poll)
    db.session.flush()
    for opt in options[:6]:
        db.session.add(PollOption(poll_id=poll.id, text=opt))
    db.session.commit()

    return jsonify(success=True, poll_id=poll.id)


@views.route('/class/<int:class_id>/polls/<int:poll_id>/vote', methods=['POST'])
@login_required
def class_poll_vote(class_id, poll_id):
    classroom = _classroom_access_or_403(class_id)
    if not classroom:
        return jsonify(success=False, error="Access denied"), 403

    poll = Poll.query.filter_by(id=poll_id, classroom_id=classroom.id).first_or_404()
    data = request.get_json() or {}
    option_id = data.get('option_id')
    option = PollOption.query.filter_by(id=option_id, poll_id=poll.id).first()
    if not option:
        return jsonify(success=False, error="Invalid option"), 400

    # one vote per poll per user
    existing = (
        db.session.query(PollVote)
        .join(PollOption)
        .filter(PollOption.poll_id == poll.id, PollVote.user_id == current_user.id)
        .first()
    )
    if existing:
        existing.option_id = option.id
    else:
        db.session.add(PollVote(option_id=option.id, user_id=current_user.id))

    db.session.commit()

    # return counts
    counts = {
        opt.id: len(opt.votes)
        for opt in poll.options
    }
    return jsonify(success=True, counts=counts)


@views.route('/class/<int:class_id>/post', methods=['POST'])
@login_required
def create_class_post(class_id):
    classroom = ClassRoom.query.get_or_404(class_id)
    if (current_user.id != classroom.teacher_id) and (not current_user.is_admin):
        flash('Only teacher or admin can post to the class feed.', 'danger')
        return redirect(url_for('views.class_feed', class_id=class_id))

    content = (request.form.get('content') or '').strip()
    title = (request.form.get('title') or '').strip()
    if not content:
        flash('Post content is required.', 'danger')
        return redirect(url_for('views.class_feed', class_id=class_id))

    post = ClassPost(
        title=title or None,
        content=content,
        user_id=current_user.id,
        classroom_id=classroom.id
    )
    db.session.add(post)
    db.session.commit()
    flash('Post added to class feed.', 'success')
    return redirect(url_for('views.class_feed', class_id=class_id))


@views.route('/messages/<int:user_id>/read', methods=['POST'])
@login_required
def messages_mark_read(user_id):
    """Mark messages from given user as read (HTTP fallback)."""
    other_user = User.query.get_or_404(user_id)
    msgs = Message.query.filter_by(
        sender_id=other_user.id,
        receiver_id=current_user.id,
        is_read=False
    ).all()
    changed = False
    for m in msgs:
        m.is_read = True
        changed = True
    if changed:
        db.session.commit()
    return jsonify(success=True, unread=Message.query.filter_by(receiver_id=current_user.id, is_read=False).count())


@views.route('/messages/unread-summary', methods=['GET'])
@login_required
def messages_unread_summary():
    """Return total unread and per-sender counts."""
    rows = (
        db.session.query(Message.sender_id, func.count(Message.id))
        .filter(Message.receiver_id == current_user.id, Message.is_read.is_(False))
        .group_by(Message.sender_id)
        .all()
    )
    per_sender = {sid: count for sid, count in rows}
    total = sum(per_sender.values())
    return jsonify(total=total, per_sender=per_sender)


@views.route('/attachments/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    att = NoteAttachment.query.get_or_404(attachment_id)
    note = att.note
    if note.user_id != current_user.id and not note.is_public:
        flash("You don't have access to this file.", 'danger')
        return redirect(url_for('views.home'))
    upload_dir = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, '..', 'uploads')
    return send_from_directory(upload_dir, att.filepath, as_attachment=True, download_name=att.filename)


# --------- USER SEARCH (AJAX for messages.html search box) ---------

@views.route('/user-search')
@login_required
def user_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])

    users = User.query.filter(
        User.id != current_user.id,
        User.first_name.ilike(f"%{q}%")
    ).order_by(User.first_name.asc()).limit(10).all()

    return jsonify([
        {'id': u.id, 'first_name': u.first_name, 'email': u.email}
        for u in users
    ])


