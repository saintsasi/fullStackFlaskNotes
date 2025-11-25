// -------------------- QUILL EDITOR SYNC --------------------
var quillElement = document.getElementById('editor-container');
if (quillElement) {
  var quill = new Quill('#editor-container', {
    theme: 'snow',
    placeholder: 'Write your note...',
    modules: {
      toolbar: [
        ['bold', 'italic', 'underline'],
        [{ 'list': 'ordered' }, { 'list': 'bullet' }],
        ['link']
      ]
    }
  });

  var noteForm = document.getElementById('note-form') || document.getElementById('edit-note-form');
  if (noteForm) {
    noteForm.onsubmit = function () {
      var hidden = document.getElementById('note_content_hidden') ||
                   document.getElementById('note-content-hidden');
      if (hidden) {
        hidden.value = quill.root.innerHTML;
      }
      return true;
    };
  }
}

// -------------------- DELETE NOTE --------------------
function deleteNote(noteId) {
  if (!confirm("Are you sure you want to delete this note?")) return;
  fetch('/delete-note', {
    method: 'POST',
    body: JSON.stringify({ noteId: noteId }),
    headers: { 'Content-Type': 'application/json' }
  }).then(() => { location.reload(); });
}

// -------------------- REACTIONS --------------------
function react(noteId, type) {
  fetch('/react', {
    method: 'POST',
    body: JSON.stringify({ noteId: noteId, type: type }),
    headers: { 'Content-Type': 'application/json' }
  }).then(() => { location.reload(); });
}
