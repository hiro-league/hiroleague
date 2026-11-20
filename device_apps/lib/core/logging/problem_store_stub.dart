/// Web / non-IO: problems wait in memory only (a reload loses what was never sent).
class ProblemStore {
  // The same shape as the file one (problem_store_io.dart); here there is no folder.
  ProblemStore({Future<dynamic> Function()? folder});

  Future<List<Map<String, dynamic>>> read() async => const [];

  Future<void> write(List<Map<String, dynamic>> problems) async {}
}
