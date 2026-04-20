import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'application/app_controller.dart';
import 'application/app_services.dart';
import 'core/app_release.dart';
import 'core/models/app_preferences.dart';
import 'presentation/screens/bootstrap_screen.dart';
import 'presentation/screens/task_detail_shell_screen.dart';
import 'presentation/widgets/startup_failure_view.dart';

ThemeData _buildHomeflowTheme({
  required Brightness brightness,
  required Color seedColor,
}) {
  final scheme = ColorScheme.fromSeed(
    seedColor: seedColor,
    brightness: brightness,
  );

  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: brightness == Brightness.light
        ? const Color(0xFFF6F8F7)
        : const Color(0xFF101414),
    cardTheme: CardThemeData(
      elevation: 0,
      color: scheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.55)),
      ),
    ),
    appBarTheme: AppBarTheme(
      centerTitle: false,
      elevation: 0,
      scrolledUnderElevation: 0,
      backgroundColor: Colors.transparent,
      foregroundColor: scheme.onSurface,
      surfaceTintColor: Colors.transparent,
    ),
    navigationBarTheme: NavigationBarThemeData(
      elevation: 0,
      backgroundColor: scheme.surface,
      indicatorColor: scheme.secondaryContainer,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w700
              : FontWeight.w500,
        ),
      ),
    ),
  );
}

ThemeMode _themeModeFromPreference(AppThemeMode mode) {
  switch (mode) {
    case AppThemeMode.system:
      return ThemeMode.system;
    case AppThemeMode.light:
      return ThemeMode.light;
    case AppThemeMode.dark:
      return ThemeMode.dark;
  }
}

class HomeflowApp extends StatelessWidget {
  const HomeflowApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Homeflow Mobile',
      theme: _buildHomeflowTheme(
        brightness: Brightness.light,
        seedColor: const Color(0xFF0F766E),
      ),
      darkTheme: _buildHomeflowTheme(
        brightness: Brightness.dark,
        seedColor: const Color(0xFF14B8A6),
      ),
      home: const _AppBootstrapScope(),
    );
  }
}

class _AppBootstrapScope extends StatefulWidget {
  const _AppBootstrapScope();

  @override
  State<_AppBootstrapScope> createState() => _AppBootstrapScopeState();
}

class _AppBootstrapScopeState extends State<_AppBootstrapScope> {
  late Future<AppServices> _bootstrapFuture;

  @override
  void initState() {
    super.initState();
    _bootstrapFuture = AppServices.bootstrap();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AppServices>(
      future: _bootstrapFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const _LaunchScreen();
        }

        if (snapshot.hasError || !snapshot.hasData) {
          return StartupFailureView(
            title: 'App startup failed',
            message:
                'Homeflow could not finish loading on this device. Try again to continue.',
            diagnostics: _buildBootstrapDiagnostics(
              snapshot.error,
              snapshot.stackTrace,
            ),
            onRetry: () {
              setState(() {
                _bootstrapFuture = AppServices.bootstrap();
              });
            },
          );
        }

        return _HomeflowAppShell(services: snapshot.data!);
      },
    );
  }

  String _buildBootstrapDiagnostics(
    Object? error,
    StackTrace? stackTrace,
  ) {
    final buffer = StringBuffer()
      ..writeln('Homeflow Mobile startup diagnostics')
      ..writeln('stage: app_bootstrap')
      ..writeln('release: $appReleaseLabel')
      ..writeln('timestamp_utc: ${DateTime.now().toUtc().toIso8601String()}');

    if (error != null) {
      buffer
        ..writeln('error_type: ${error.runtimeType}')
        ..writeln('error: $error');
    } else {
      buffer.writeln('error: unknown bootstrap failure');
    }

    if (stackTrace != null) {
      buffer
        ..writeln('stack_trace:')
        ..writeln(stackTrace);
    }

    return buffer.toString().trim();
  }
}

class _HomeflowAppShell extends StatelessWidget {
  const _HomeflowAppShell({required this.services});

  final AppServices services;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<AppController>(
      create: (_) => AppController(services)..initialize(),
      child: Consumer<AppController>(
        builder: (context, controller, _) => MaterialApp(
          title: 'Homeflow Mobile',
          theme: _buildHomeflowTheme(
            brightness: Brightness.light,
            seedColor: const Color(0xFF0F766E),
          ),
          darkTheme: _buildHomeflowTheme(
            brightness: Brightness.dark,
            seedColor: const Color(0xFF14B8A6),
          ),
          themeMode: _themeModeFromPreference(controller.themeModePreference),
          routes: <String, WidgetBuilder>{
            TaskDetailShellScreen.routeName: (_) =>
                const TaskDetailShellScreen(),
          },
          home: const BootstrapScreen(),
        ),
      ),
    );
  }
}

class _LaunchScreen extends StatelessWidget {
  const _LaunchScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(28),
              child: Image.asset(
                'assets/homeflow_logo.jpg',
                width: 144,
                height: 144,
                fit: BoxFit.cover,
              ),
            ),
            const SizedBox(height: 20),
            const CircularProgressIndicator(),
          ],
        ),
      ),
    );
  }
}
