import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'application/app_controller.dart';
import 'application/app_services.dart';
import 'core/models/app_preferences.dart';
import 'presentation/screens/bootstrap_screen.dart';
import 'presentation/screens/task_detail_shell_screen.dart';

class HomeflowApp extends StatelessWidget {
  const HomeflowApp({
    required this.services,
    super.key,
  });

  final AppServices services;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<AppController>(
      create: (_) => AppController(services)..initialize(),
      child: Consumer<AppController>(
        builder: (context, controller, _) => MaterialApp(
          title: 'Homeflow Mobile',
          theme: ThemeData(
            colorScheme: ColorScheme.fromSeed(
              seedColor: const Color(0xFF0F766E),
              brightness: Brightness.light,
            ),
            useMaterial3: true,
          ),
          darkTheme: ThemeData(
            colorScheme: ColorScheme.fromSeed(
              seedColor: const Color(0xFF14B8A6),
              brightness: Brightness.dark,
            ),
            useMaterial3: true,
          ),
          themeMode: _toFlutterThemeMode(controller.themeModePreference),
          routes: <String, WidgetBuilder>{
            TaskDetailShellScreen.routeName: (_) => const TaskDetailShellScreen(),
          },
          home: const BootstrapScreen(),
        ),
      ),
    );
  }

  ThemeMode _toFlutterThemeMode(AppThemeMode mode) {
    switch (mode) {
      case AppThemeMode.system:
        return ThemeMode.system;
      case AppThemeMode.light:
        return ThemeMode.light;
      case AppThemeMode.dark:
        return ThemeMode.dark;
    }
  }
}
