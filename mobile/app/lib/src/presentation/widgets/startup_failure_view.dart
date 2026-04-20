import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class StartupFailureView extends StatelessWidget {
  const StartupFailureView({
    required this.title,
    required this.message,
    required this.onRetry,
    this.diagnostics,
    super.key,
  });

  final String title;
  final String message;
  final String? diagnostics;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final canCopy = diagnostics != null && diagnostics!.trim().isNotEmpty;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        message,
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                      const SizedBox(height: 20),
                      Wrap(
                        spacing: 12,
                        runSpacing: 12,
                        children: [
                          FilledButton(
                            onPressed: onRetry,
                            child: const Text('Try again'),
                          ),
                          if (canCopy)
                            OutlinedButton.icon(
                              onPressed: () => _copyDiagnostics(context),
                              icon: const Icon(Icons.copy_outlined),
                              label: const Text('Copy details'),
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
      ),
    );
  }

  Future<void> _copyDiagnostics(BuildContext context) async {
    final payload = diagnostics;
    if (payload == null || payload.trim().isEmpty) {
      return;
    }

    await Clipboard.setData(ClipboardData(text: payload));
    if (!context.mounted) {
      return;
    }

    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Diagnostics copied')));
  }
}
