import 'package:flutter/material.dart';

import '../../models/admin_user.dart';
import '../../models/ingest_entry.dart';
import '../../services/admin_service.dart';

class AdminUsersPage extends StatefulWidget {
  const AdminUsersPage({super.key, required this.service, this.onClose});

  final AdminService service;
  final VoidCallback? onClose;

  @override
  State<AdminUsersPage> createState() => _AdminUsersPageState();
}

class _AdminUsersPageState extends State<AdminUsersPage> {
  List<AdminUser> _users = const [];
  bool _loading = true;
  String? _deletingEmail;
  String? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final users = await widget.service.fetchUsers();
      if (!mounted) return;
      setState(() {
        _users = users;
        _loading = false;
      });
    } on AdminException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  Future<void> _edit(AdminUser user) async {
    final result = await showDialog<_UserEditResult>(
      context: context,
      builder: (context) => _UserEditDialog(user: user),
    );
    if (result == null) return;
    try {
      await widget.service.updateUser(
        currentEmail: user.email,
        email: result.email,
        role: result.role,
        password: result.password,
      );
      await _refresh();
    } on AdminException catch (error) {
      _showError(error.message);
    }
  }

  Future<void> _delete(AdminUser user) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete user account?'),
        content: Text(
          'Delete ${user.email} and all of their feedback and chat history?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _deletingEmail = user.email);
    try {
      await widget.service.deleteUser(user.email);
      await _refresh();
    } on AdminException catch (error) {
      _showError(error.message);
    } finally {
      if (mounted) setState(() => _deletingEmail = null);
    }
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Manage users'),
        leading: widget.onClose == null
            ? null
            : IconButton(
                onPressed: widget.onClose,
                tooltip: 'Back to dashboard',
                icon: const Icon(Icons.arrow_back),
              ),
        actions: [
          IconButton(
            onPressed: _loading ? null : _refresh,
            tooltip: 'Refresh users',
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? Center(child: Text(_error!))
          : RefreshIndicator(
              onRefresh: _refresh,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  const Text(
                    'Account management does not require the paper-upload secret.',
                    style: TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 12),
                  for (final user in _users)
                    Card(
                      child: ListTile(
                        leading: Icon(
                          user.role == 'admin'
                              ? Icons.admin_panel_settings_outlined
                              : Icons.person_outline,
                        ),
                        title: Text(user.email),
                        subtitle: Text(
                          '${user.role} • ${user.feedbackCount} feedback • '
                          '${user.conversationCount} conversations • '
                          '${user.messageCount} messages',
                        ),
                        isThreeLine: true,
                        trailing: Wrap(
                          children: [
                            IconButton(
                              onPressed: () => _edit(user),
                              tooltip: 'Edit user',
                              icon: const Icon(Icons.edit_outlined),
                            ),
                            if (user.role != 'admin')
                              IconButton(
                                onPressed: _deletingEmail == null
                                    ? () => _delete(user)
                                    : null,
                                tooltip: 'Delete user',
                                icon: _deletingEmail == user.email
                                    ? const SizedBox(
                                        width: 20,
                                        height: 20,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                        ),
                                      )
                                    : const Icon(Icons.delete_outline),
                              ),
                          ],
                        ),
                      ),
                    ),
                ],
              ),
            ),
    );
  }
}

class _UserEditResult {
  const _UserEditResult(this.email, this.role, this.password);

  final String email;
  final String role;
  final String password;
}

class _UserEditDialog extends StatefulWidget {
  const _UserEditDialog({required this.user});

  final AdminUser user;

  @override
  State<_UserEditDialog> createState() => _UserEditDialogState();
}

class _UserEditDialogState extends State<_UserEditDialog> {
  late final TextEditingController _email;
  late final TextEditingController _password;
  late String _role;

  @override
  void initState() {
    super.initState();
    _email = TextEditingController(text: widget.user.email);
    _password = TextEditingController();
    _role = widget.user.role;
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Edit user account'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _email,
              decoration: const InputDecoration(labelText: 'Email or username'),
            ),
            DropdownButtonFormField<String>(
              initialValue: _role,
              decoration: const InputDecoration(labelText: 'Role'),
              items: const [
                DropdownMenuItem(value: 'user', child: Text('User')),
                DropdownMenuItem(value: 'admin', child: Text('Administrator')),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _role = value);
              },
            ),
            TextField(
              controller: _password,
              obscureText: true,
              decoration: const InputDecoration(
                labelText: 'New password (optional)',
              ),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            final email = _email.text.trim();
            if (email.isNotEmpty) {
              Navigator.pop(
                context,
                _UserEditResult(email, _role, _password.text),
              );
            }
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
