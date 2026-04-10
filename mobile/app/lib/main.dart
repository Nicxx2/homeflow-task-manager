import 'package:flutter/widgets.dart';

import 'src/app.dart';
import 'src/application/app_services.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final services = await AppServices.bootstrap();
  runApp(HomeflowApp(services: services));
}
