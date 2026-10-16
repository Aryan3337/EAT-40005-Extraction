import 'package:flutter/material.dart';

import '../../app/app_localizations.dart';
import '../../services/auth_service.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({
    super.key,
    required this.onSignIn,
    this.onRegister = _defaultRegister,
    this.strings = const AppLocalizations('en'),
    this.onLanguageChanged,
  });

  final Future<void> Function(String email, String password, bool rememberMe)
  onSignIn;
  final Future<void> Function(RegistrationDetails details, bool rememberMe)
  onRegister;

  static Future<void> _defaultRegister(
    RegistrationDetails details,
    bool rememberMe,
  ) async {}
  final AppLocalizations strings;
  final ValueChanged<String>? onLanguageChanged;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _formKey = GlobalKey<FormState>();
  final _identifierController = TextEditingController();
  final _usernameController = TextEditingController();
  final _phoneCountryCodeController = TextEditingController(text: '+1');
  final _phoneController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _obscurePassword = true;
  bool _rememberMe = true;
  bool _isSubmitting = false;
  bool _isRegistering = false;

  @override
  void dispose() {
    _identifierController.dispose();
    _usernameController.dispose();
    _phoneCountryCodeController.dispose();
    _phoneController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate() || _isSubmitting) return;
    setState(() => _isSubmitting = true);
    try {
      if (_isRegistering) {
        await widget.onRegister(
          RegistrationDetails(
            username: _usernameController.text.trim(),
            email: _identifierController.text.trim(),
            phoneCountryCode: _phoneCountryCodeController.text.trim(),
            phoneNumber: _phoneController.text.trim(),
            password: _passwordController.text,
          ),
          _rememberMe,
        );
      } else {
        await widget.onSignIn(
          _identifierController.text.trim(),
          _passwordController.text,
          _rememberMe,
        );
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            error is AuthException
                ? error.message
                : widget.strings.text('invalidCredentials'),
          ),
        ),
      );
    } finally {
      if (mounted) setState(() => _isSubmitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: DecoratedBox(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFEAF2FF), Color(0xFFF7F9FC)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Card(
                  elevation: 8,
                  shadowColor: const Color(0x1A183B66),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(22),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(28, 28, 28, 24),
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
                            widget.strings.text(
                              _isRegistering ? 'createAccount' : 'welcomeBack',
                            ),
                            style: theme.textTheme.headlineMedium?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: const Color(0xFF172B4D),
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            widget.strings.text(
                              _isRegistering
                                  ? 'registerDescription'
                                  : 'loginDescription',
                            ),
                            style: theme.textTheme.bodyLarge?.copyWith(
                              color: const Color(0xFF637078),
                            ),
                          ),
                          const SizedBox(height: 34),
                          if (_isRegistering) ...[
                            TextFormField(
                              controller: _usernameController,
                              textInputAction: TextInputAction.next,
                              autofillHints: const [AutofillHints.newUsername],
                              decoration: InputDecoration(
                                labelText: widget.strings.text('username'),
                                hintText: 'yourname',
                                prefixIcon: const Icon(Icons.alternate_email),
                              ),
                              validator: (value) {
                                final username = value?.trim() ?? '';
                                if (!RegExp(
                                  r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{2,29}$',
                                ).hasMatch(username)) {
                                  return widget.strings.text(
                                    'usernameRequirements',
                                  );
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 16),
                          ],
                          TextFormField(
                            controller: _identifierController,
                            keyboardType: TextInputType.emailAddress,
                            textInputAction: TextInputAction.next,
                            autofillHints: [
                              if (_isRegistering)
                                AutofillHints.email
                              else
                                AutofillHints.username,
                            ],
                            decoration: InputDecoration(
                              labelText: widget.strings.text(
                                _isRegistering ? 'email' : 'usernameEmail',
                              ),
                              hintText: 'name@example.com',
                              prefixIcon: const Icon(Icons.mail_outline),
                            ),
                            validator: (value) {
                              final identifier = value?.trim() ?? '';
                              if (identifier.isEmpty) {
                                return widget.strings.text('enterUsername');
                              }
                              if (_isRegistering &&
                                  !_isValidEmail(identifier)) {
                                return widget.strings.text('enterEmail');
                              }
                              return null;
                            },
                          ),
                          if (_isRegistering) ...[
                            const SizedBox(height: 16),
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                SizedBox(
                                  width: 132,
                                  child: TextFormField(
                                    controller: _phoneCountryCodeController,
                                    keyboardType: TextInputType.phone,
                                    textInputAction: TextInputAction.next,
                                    decoration: InputDecoration(
                                      labelText: widget.strings.text(
                                        'countryCode',
                                      ),
                                      hintText: '+61',
                                    ),
                                    validator: (value) {
                                      if (!RegExp(
                                        r'^\+[1-9][0-9]{0,3}$',
                                      ).hasMatch((value ?? '').trim())) {
                                        return widget.strings.text(
                                          'enterCountryCode',
                                        );
                                      }
                                      return null;
                                    },
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: TextFormField(
                                    controller: _phoneController,
                                    keyboardType: TextInputType.phone,
                                    textInputAction: TextInputAction.next,
                                    autofillHints: const [
                                      AutofillHints.telephoneNumber,
                                    ],
                                    decoration: InputDecoration(
                                      labelText: widget.strings.text(
                                        'phoneNumber',
                                      ),
                                      hintText: '555 123 4567',
                                      prefixIcon: const Icon(
                                        Icons.phone_outlined,
                                      ),
                                    ),
                                    validator: (value) {
                                      final digits = (value ?? '').replaceAll(
                                        RegExp(r'\D'),
                                        '',
                                      );
                                      if (digits.length < 4 ||
                                          digits.length > 14) {
                                        return widget.strings.text(
                                          'enterValidPhone',
                                        );
                                      }
                                      return null;
                                    },
                                  ),
                                ),
                              ],
                            ),
                          ],
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
                              if (_isRegistering && value!.length < 8) {
                                return widget.strings.text('passwordTooShort');
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
                                padding: const EdgeInsets.symmetric(
                                  vertical: 17,
                                ),
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
                                  : Text(
                                      widget.strings.text(
                                        _isRegistering
                                            ? 'createAccount'
                                            : 'signIn',
                                      ),
                                    ),
                            ),
                          ),
                          const SizedBox(height: 12),
                          Center(
                            child: TextButton(
                              onPressed: _isSubmitting
                                  ? null
                                  : () => setState(
                                      () => _isRegistering = !_isRegistering,
                                    ),
                              child: Text(
                                widget.strings.text(
                                  _isRegistering
                                      ? 'alreadyHaveAccount'
                                      : 'needAccount',
                                ),
                              ),
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
          ),
        ),
      ),
    );
  }

  bool _isValidEmail(String email) {
    final localPart = email.split('@').first;
    return RegExp(
      r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$",
    ).hasMatch(email) &&
        email.length <= 254 &&
        localPart.length <= 64;
  }
}
