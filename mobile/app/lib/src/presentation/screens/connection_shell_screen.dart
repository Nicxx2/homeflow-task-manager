import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../application/app_controller.dart';
import '../../core/models/connection_settings.dart';

class ConnectionShellScreen extends StatefulWidget {
  const ConnectionShellScreen({super.key});

  @override
  State<ConnectionShellScreen> createState() => _ConnectionShellScreenState();
}

class _ConnectionShellScreenState extends State<ConnectionShellScreen> {
  final _formKey = GlobalKey<FormState>();
  final _hostController = TextEditingController();
  final _portController = TextEditingController(text: '8000');
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  String _scheme = 'http';
  bool _seededFromController = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_seededFromController) {
      return;
    }
    final settings = context.read<AppController>().connectionSettings;
    if (settings != null) {
      _scheme = settings.scheme;
      _hostController.text = settings.host;
      _portController.text = settings.port.toString();
    }
    _seededFromController = true;
  }

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AppController>();
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Center(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(24),
                        child: Image.asset(
                          'assets/homeflow_logo.jpg',
                          width: 140,
                          height: 140,
                          fit: BoxFit.cover,
                        ),
                      ),
                    ),
                    const SizedBox(height: 24),
                    Text(
                      'Connect to your Homeflow server',
                      style: theme.textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Connect to your self-hosted Homeflow server, then sign in with your account to load today and upcoming tasks.',
                      style: theme.textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 24),
                    DropdownButtonFormField<String>(
                      initialValue: _scheme,
                      decoration: const InputDecoration(labelText: 'Scheme'),
                      items: const [
                        DropdownMenuItem(value: 'http', child: Text('HTTP')),
                        DropdownMenuItem(value: 'https', child: Text('HTTPS')),
                      ],
                      onChanged: (value) {
                        setState(() {
                          _scheme = value ?? 'http';
                        });
                      },
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _hostController,
                      decoration: const InputDecoration(
                        labelText: 'Hostname or IP',
                      ),
                      onChanged: (_) => setState(() {}),
                      validator: (value) {
                        if (value == null || value.trim().isEmpty) {
                          return 'Host is required.';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _portController,
                      decoration: const InputDecoration(labelText: 'Port'),
                      keyboardType: TextInputType.number,
                      onChanged: (_) => setState(() {}),
                      validator: (value) {
                        final port = int.tryParse(value ?? '');
                        if (port == null || port < 1 || port > 65535) {
                          return 'Use a valid port.';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _emailController,
                      decoration: const InputDecoration(labelText: 'Email'),
                      keyboardType: TextInputType.emailAddress,
                      validator: (value) {
                        if (value == null || !value.contains('@')) {
                          return 'Use a valid email.';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _passwordController,
                      decoration: const InputDecoration(labelText: 'Password'),
                      obscureText: true,
                      validator: (value) {
                        if (value == null || value.isEmpty) {
                          return 'Password is required.';
                        }
                        return null;
                      },
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Derived URL: ${ConnectionSettings(scheme: _scheme, host: _hostController.text.trim().isEmpty ? 'server-host' : _hostController.text.trim(), port: int.tryParse(_portController.text) ?? 8000).baseUrl}',
                      style: theme.textTheme.bodySmall,
                    ),
                    if (controller.errorMessage != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        controller.errorMessage!,
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ],
                    const SizedBox(height: 24),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: controller.isAuthenticating
                                ? null
                                : _handleTestConnection,
                            child: const Text('Test connection'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: FilledButton(
                            onPressed: controller.isAuthenticating
                                ? null
                                : _handleSignIn,
                            child: controller.isAuthenticating
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('Sign in'),
                          ),
                        ),
                      ],
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

  Future<void> _handleTestConnection() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    final controller = context.read<AppController>();
    final okay = await controller.testConnection(
      ConnectionSettings(
        scheme: _scheme,
        host: _hostController.text.trim(),
        port: int.parse(_portController.text),
      ),
    );
    if (!mounted) {
      return;
    }
    final message = okay ? 'Connection succeeded.' : 'Connection failed.';
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _handleSignIn() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    await context.read<AppController>().signIn(
          scheme: _scheme,
          host: _hostController.text,
          port: int.parse(_portController.text),
          email: _emailController.text,
          password: _passwordController.text,
        );
  }
}
