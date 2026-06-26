from django.urls import path
from . import views

urlpatterns = [
    path('', views.po_sheet, name='po_sheet'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('search-vendor/', views.search_vendor, name='search_vendor'),
    path('select-vendor/', views.select_vendor, name='select_vendor'),
    path('search-subcategory/', views.search_subcategory, name='search_subcategory'),
    path('add-po-item/', views.add_po_item, name='add_po_item'),
    path('add-manual-item/', views.add_manual_item, name='add_manual_item'),
    path('update-po-item/<int:item_id>/', views.update_po_item, name='update_po_item'),
    path('delete-po-item/<int:item_id>/', views.delete_po_item, name='delete_po_item'),
    path('admin-budget/', views.admin_budget, name='admin_budget'),
    path('budget-spent-details/', views.budget_spent_details, name='budget_spent_details'),
    path('update-price-range/', views.update_price_range, name='update_price_range'),
    path('add-price-range/', views.add_price_range, name='add_price_range'),
    path('delete-price-range/', views.delete_price_range, name='delete_price_range'),
    path('submit-po/', views.submit_po, name='submit_po'),
    path('new-po/', views.new_po, name='new_po'),
    path('update-po-fields/', views.update_po_fields, name='update_po_fields'),
    path('save-po/', views.save_po, name='save_po'),
    path('preview-po/', views.preview_po, name='preview_po'),
    path('send-po/', views.send_po, name='send_po'),
    
    path('records/', views.all_records, name='all_records'),
    path('export-po-csv/<int:po_id>/', views.export_po_csv, name='export_po_csv'),
    
    # Size Manager
    path('size-manager/', views.size_manager, name='size_manager'),
    path('get-subcategory-sizes/<str:subcategory_id>/', views.get_subcategory_sizes, name='get_subcategory_sizes'),
    path('get-subcategory-ranges/<str:subcategory_id>/', views.get_subcategory_ranges, name='get_subcategory_ranges'),
    path('add-subcategory-sizes/', views.add_subcategory_sizes, name='add_subcategory_sizes'),
    path('remove-subcategory-size/', views.remove_subcategory_size, name='remove_subcategory_size'),
    
    # User Manager
    path('manage-users/', views.manage_users, name='manage_users'),
    path('delete-user/<int:user_id>/', views.delete_user, name='delete_user'),
    path('delete-po/<int:po_id>/', views.delete_po, name='delete_po'),
    path('upload-excel/', views.upload_excel, name='upload_excel'),
]

