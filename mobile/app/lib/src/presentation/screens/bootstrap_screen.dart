import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../application/app_controller.dart';
import 'connection_shell_screen.dart';
import 'home_shell_screen.dart';
import '../widgets/startup_failure_view.dart';

class BootstrapScreen extends StatelessWidget {
  const BootstrapScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<AppController>(
      builder: (context, controller, _) {
        if (controller.isInitializing) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }

        if (controller.isAuthenticated) {
          return const HomeShellScreen();
        }

        if (controller.hasInitializationFailure) {
          return StartupFailureView(
            title: 'App startup failed',
            message:
                'Homeflow could not finish loading on this device. Try again to continue.',
            diagnostics: controller.initializationDiagnostics,
            onRetry: controller.initialize,
          );
        }

        return const ConnectionShellScreen();
      },
    );
  }
}
