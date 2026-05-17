from django.urls import path

from . import views


app_name = 'spoeqi'

urlpatterns = [
    path('',                   views.index,    name='index'),
    path('new/',               views.create,   name='create'),

    # Metapact — must precede the catch-all <slug:slug>/ below
    path('metapact/',                       views.metapact_list,    name='metapact_list'),
    path('metapact/new/',                   views.metapact_create,  name='metapact_create'),
    path('metapact/tournament/',            views.metapact_tournament,
                                                                    name='metapact_tournament'),
    path('metapact/tournament/stream/',     views.metapact_tournament_stream,
                                                                    name='metapact_tournament_stream'),
    path('metapact/<slug:slug>/',           views.metapact_detail,  name='metapact_detail'),
    path('metapact/<slug:slug>/expand/',    views.metapact_expand,  name='metapact_expand'),
    path('metapact/<slug:slug>/bytes',      views.metapact_bytes,   name='metapact_bytes'),
    path('metapact/<slug:slug>/chat/',      views.metapact_chat,    name='metapact_chat'),
    path('metapact/<slug:slug>/chat/reply/',views.metapact_chat_reply,
                                                                    name='metapact_chat_reply'),
    path('metapact/<slug:slug>/evolve/',    views.metapact_evolve,  name='metapact_evolve'),
    path('metapact/<slug:slug>/evolve/stream/',
                                              views.metapact_evolve_stream,
                                              name='metapact_evolve_stream'),
    path('metapact/<slug:slug>/save/',      views.metapact_save_winner,
                                                                    name='metapact_save_winner'),
    path('metapact/<slug:slug>/delete/',    views.metapact_delete,  name='metapact_delete'),

    # Class-4 quine toolkit (must precede the catch-all <slug:slug>/ below).
    path('quine/',                       views.quine_index,    name='quine_index'),
    path('quine/search/',                views.quine_search,   name='quine_search'),
    path('quine/image/',                 views.quine_image,    name='quine_image'),
    path('quine/image/save/',            views.quine_image_save,
                                                                name='quine_image_save'),
    path('quine/<int:pk>/',              views.quine_detail,   name='quine_detail'),
    path('quine/<int:pk>/refine/',       views.quine_refine,   name='quine_refine'),
    path('quine/<int:pk>/delete/',       views.quine_delete,   name='quine_delete'),
    path('quine/<int:pk>/seed.bin',      views.quine_seed_bytes,
                                                                name='quine_seed_bytes'),
    path('quine/<int:pk>/to-pact/',      views.quine_to_pact,  name='quine_to_pact'),
    path('quine/<int:pk>/streams/',                  views.quine_streams,
                                                            name='quine_streams'),
    path('quine/<int:pk>/streams/L<int:level>.bin',  views.quine_stream_download,
                                                            name='quine_stream_download'),
    path('quine/<int:pk>/streams/L<int:level>/taxon/',
                                                          views.quine_chain_to_taxon,
                                                          name='quine_chain_to_taxon'),
    path('quine/<int:pk>/streams/bundle.zip',        views.quine_streams_bundle,
                                                            name='quine_streams_bundle'),

    path('<slug:slug>/',       views.detail,   name='detail'),
    path('<slug:slug>/delete/', views.delete,  name='delete'),
    path('<slug:slug>/export-tile/<int:component>/',
                                views.export_tile_to_automaton,
                                name='export_tile'),
    path('<slug:slug>/tap/<int:component>/<int:generation>/<int:n_bytes>/',
                                views.keystream_tap,
                                name='tap'),
    path('<slug:slug>/oracle/', views.oracle,    name='oracle'),
    path('<slug:slug>/textmask/', views.textmask, name='textmask'),
    path('<slug:slug>/chain/',           views.chain,         name='chain'),
    path('<slug:slug>/chain/evolve/',    views.chain_evolve,  name='chain_evolve'),
    path('<slug:slug>/evolve/',   views.evolve,   name='evolve'),
    path('<slug:slug>/workspace/',                 views.workspace_index,
                                                    name='workspace'),
    path('<slug:slug>/workspace/<str:app>/<int:tick>.elf',
                                                    views.workspace_app_elf,
                                                    name='workspace_app_elf'),
    # Bearer-token download path — no login needed, just (slug, token).
    # Token is shown on the workspace index page.
    path('<slug:slug>/workspace/t/<str:token>/<str:app>/<int:tick>.elf',
                                                    views.workspace_app_elf_token,
                                                    name='workspace_app_elf_token'),
    path('album/new/',            views.album_new, name='album_new'),
]
