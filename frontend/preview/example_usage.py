"""
Örnek kullanım: çift tıklamayı tam ekran önizlemeye ve controller.open_at_index'e bağlama.
MainWindow'a entegre edin: on_item_double_click → CollectionModel oluştur → open_at_index(i).
"""
from __future__ import annotations

# -----------------------------------------------------------------------------
# ÖRNEK: on_item_double_click(file_path, collection)
# -----------------------------------------------------------------------------
# Adli uygulamada (oturum, geçerli klasör düğümleri, tıklanan dizin) bulunur — dosya yolu yoktur.

# Yani: on_item_double_click(session, current_folder_nodes, clicked_index, case_dir, evidence_id)
#
# def on_item_double_click(session, current_folder_nodes, clicked_index, case_dir, evidence_id):
# collection = CollectionModel(current_folder_nodes, current_index=clicked_index)
# if not getattr(main_window, "_preview_controller", None):
# main_window._preview_controller = PreviewController(
# session, case_dir, evidence_id, parent_widget=main_window
# )
# main_window._preview_controller.set_collection(collection)
# main_window._preview_controller.open_at_index(clicked_index)
# ------------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# ÖRNEK: controller.open_at_index(i)
# -----------------------------------------------------------------------------
# controller.open_at_index(5)
# → collection.jump_to(5)
# → _cancel_token.cancel(); Yeni CancellationToken()
# → _load_current_item()
# → item = collection.get_current()
# → viewer_type = MediaRouter.route(item)
# → viewer = _create_viewer(viewer_type, item) # ImageViewer / VideoPlayer / vb.
# → _window.set_viewer_widget(viewer)
# → _schedule_prefetch() # sonraki/önceki minimum veri
# -----------------------------------------------------------------------------

def build_preview_controller(session, case_dir: str, evidence_id: str, parent_widget=None):
    """Factory for PreviewController; reuse across double-clicks."""
    from frontend.preview.preview_controller import PreviewController
    return PreviewController(session, case_dir, evidence_id, parent_widget)


def on_item_double_click(session, current_folder_nodes: list, clicked_index: int, case_dir: str, evidence_id: str, controller_holder: dict):
    """
    Call from MainWindow when user double-clicks a list/table item.
    controller_holder: e.g. {"controller": None}; we create or reuse controller.
    """
    from frontend.preview.collection_model import CollectionModel
    from frontend.preview.preview_controller import PreviewController

    collection = CollectionModel(current_folder_nodes, current_index=clicked_index)
    controller = controller_holder.get("controller")
    if controller is None:
        controller = PreviewController(session, case_dir, evidence_id, parent_widget=None)
        controller_holder["controller"] = controller
    controller.set_collection(collection)
    controller.open_at_index(clicked_index)
