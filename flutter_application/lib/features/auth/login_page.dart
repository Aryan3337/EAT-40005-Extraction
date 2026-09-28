import 'package:flutter/material.dart';

import '../../app/app_localizations.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({
    super.key,
    required this.onSignIn,
    this.strings = const AppLocalizations('en'),
    this.onLanguageChanged,
  });

  final Future<void> Function(String email, String password, bool rememberMe)
  onSignIn;
  final AppLocalizations strings;
  final ValueChanged<String>? onLanguageChanged;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _obscurePassword = true;
  bool _rememberMe = true;
  bool _isSubmitting = false;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate() || _isSubmitting) return;
    setState(() => _isSubmitting = true);
    try {
      await widget.onSignIn(
        _emailController.text.trim(),
        _passwordController.text,
        _rememberMe,
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(widget.strings.text('invalidCredentials'))),
      );
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Container(
                          width: 58,
                          height: 58,
                          decoration: BoxDecoration(
                            color: theme.colorScheme.primary,
                            borderRadius: BorderRadius.circular(18),
                          ),
                          child: const Icon(
                            Icons.account_tree_outlined,
                            color: Colors.white,
                            size: 30,
                          ),
                        ),
                        if (widget.onLanguageChanged != null)
                          LanguagePicker(
                            strings: widget.strings,
                            onChanged: widget.onLanguageChanged!,
                          ),
                      ],
                    ),
                    const SizedBox(height: 30),
                    Text(
                      widget.strings.text('welcomeBack'),
                      style: theme.textTheme.headlineMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: const Color(0xFF17212B),
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      widget.strings.text('loginDescription'),
                      style: theme.textTheme.bodyLarge?.copyWith(
                        color: const Color(0xFF637078),
                      ),
                    ),
                    const SizedBox(height: 34),
                    TextFormField(
                      controller: _emailController,
                      keyboardType: TextInputType.emailAddress,
                      textInputAction: TextInputAction.next,
                      autofillHints: const [AutofillHints.username],
                      decoration: InputDecoration(
                        labelText: widget.strings.text('usernameEmail'),
                        hintText: 'admin',
                        prefixIcon: Icon(Icons.person_outline),
                      ),
                      validator: (value) {
                        final email = value?.trim() ?? '';
                        if (email.isEmpty) {
                          return widget.strings.text('enterUsername');
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscurePassword,
                      textInputAction: TextInputAction.done,
                      autofillHints: const [AutofillHints.password],
                      onFieldSubmitted: (_) => _submit(),
                      decoration: InputDecoration(
                        labelText: widget.strings.text('password'),
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          tooltip: _obscurePassword
                              ? widget.strings.text('showPassword')
                              : widget.strings.text('hidePassword'),
                          onPressed: () => setState(
                            () => _obscurePassword = !_obscurePassword,
                          ),
                          icon: Icon(
                            _obscurePassword
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                        ),
                      ),
                      validator: (value) {
                        if ((value ?? '').isEmpty) {
                          return widget.strings.text('enterPassword');
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 8),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: _rememberMe,
                      onChanged: (value) =>
                          setState(() => _rememberMe = value ?? false),
                      title: Text(widget.strings.text('keepSignedIn')),
                      controlAffinity: ListTileControlAffinity.leading,
                    ),
                    const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _isSubmitting ? null : _submit,
                        style: FilledButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 17),
                        ),
                        child: _isSubmitting
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : Text(widget.strings.text('signIn')),
                      ),
                    ),
                    const SizedBox(height: 22),
                    Center(
                      child: Text(
                        widget.strings.text('loginFooter'),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: const Color(0xFF637078),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
